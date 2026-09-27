import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const APP_ORIGIN = "https://agunz-png.github.io";
const ADMIN_EMAIL = "agunz@bluewin.ch";
const corsHeaders = {
  "Access-Control-Allow-Origin": APP_ORIGIN,
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Vary": "Origin",
};

function reply(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

function isoDate(year: string, month: string, day: string): string {
  const y = Number(year), m = Number(month), d = Number(day);
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return "";
  return dt.toISOString().slice(0, 10);
}

function parseDates(text: string, fund: Record<string, unknown>) {
  let start = String(fund.start || "").trim();
  let end = String(fund.end || "").trim();
  if (!/^20\d{2}-\d{2}-\d{2}$/.test(start)) start = "";
  if (!/^20\d{2}-\d{2}-\d{2}$/.test(end)) end = "";
  const iso = [...text.matchAll(/20\d{2}-\d{2}-\d{2}/g)].map(m => m[0]);
  if (!start && iso.length) start = iso[0];
  if (!end && iso.length) end = iso[iso.length - 1];

  if (!start) {
    const numeric = text.match(/(?<!\d)(\d{1,2})\.(\d{1,2})\.\s*(?:[–—-]\s*(\d{1,2})\.(\d{1,2})\.\s*)?(20\d{2})/);
    if (numeric) {
      const [, day1, month1, day2, month2, year] = numeric;
      start = isoDate(year, month1, day1);
      if (day2 && month2) end = isoDate(year, month2, day2);
    }
  }
  if (!start) {
    const months: Record<string, string> = {
      januar:"01", februar:"02", märz:"03", maerz:"03", april:"04",
      mai:"05", juni:"06", juli:"07", august:"08", september:"09",
      oktober:"10", november:"11", dezember:"12",
    };
    const named = text.match(/(\d{1,2})\.?\s*(?:[–—-]\s*(\d{1,2})\.?\s*)?(januar|februar|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember)\s+(20\d{2})/i);
    if (named) {
      const [, day1, day2, monthName, year] = named;
      const month = months[monthName.toLowerCase()];
      start = isoDate(year, month, day1);
      if (day2) end = isoDate(year, month, day2);
    }
  }
  if (!start || !/^20\d{2}-\d{2}-\d{2}$/.test(start)) throw new Error("Datum nicht erkannt: " + text);
  if (!end) end = start;
  if (!/^20\d{2}-\d{2}-\d{2}$/.test(end) || end < start) throw new Error("Das Enddatum ist ungültig.");
  return { start, end };
}

const flags: Record<string, string> = {
  Schweiz:"🇨🇭", Deutschland:"🇩🇪", Österreich:"🇦🇹", Belgien:"🇧🇪",
  Bulgarien:"🇧🇬", Estland:"🇪🇪", Frankreich:"🇫🇷", Italien:"🇮🇹",
  "Vereinigtes Königreich":"🇬🇧", Ungarn:"🇭🇺", Tschechien:"🇨🇿",
  Spanien:"🇪🇸", Niederlande:"🇳🇱", Slowenien:"🇸🇮", Slowakei:"🇸🇰",
  Rumänien:"🇷🇴", Portugal:"🇵🇹", Norwegen:"🇳🇴", Finnland:"🇫🇮",
  Irland:"🇮🇪", Island:"🇮🇸", Griechenland:"🇬🇷", Schweden:"🇸🇪",
  Polen:"🇵🇱", Luxemburg:"🇱🇺", Liechtenstein:"🇱🇮", Serbien:"🇷🇸",
  Kroatien:"🇭🇷", Ukraine:"🇺🇦", Georgien:"🇬🇪", Zypern:"🇨🇾",
};

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return reply({ error: "Methode nicht erlaubt." }, 405);
  const origin = req.headers.get("Origin");
  if (origin !== APP_ORIGIN) return reply({ error: "Diese Herkunft ist nicht zugelassen." }, 403);

  const authHeader = req.headers.get("Authorization");
  const token = authHeader?.replace(/^Bearer\s+/i, "");
  const url = Deno.env.get("SUPABASE_URL");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!token || !url || !anonKey || !serviceKey) return reply({ error: "Anmeldung oder Serverkonfiguration fehlt." }, 401);

  const authClient = createClient(url, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
    global: { headers: { Authorization: authHeader! } },
  });
  const { data: { user }, error: authError } = await authClient.auth.getUser(token);
  if (authError || !user || user.email?.toLowerCase() !== ADMIN_EMAIL || !user.email_confirmed_at) {
    return reply({ error: "Für diese Herold-Aktion ist kein bestätigtes Admin-Konto angemeldet." }, 403);
  }

  let payload: { action?: string; event_id?: string };
  try { payload = await req.json(); } catch { return reply({ error: "Ungültige Anfrage." }, 400); }
  const action = payload.action;
  const eventId = String(payload.event_id || "").trim();
  if (!["approve", "reject"].includes(action || "") || !/^[A-Za-z0-9_-]{1,120}$/.test(eventId)) {
    return reply({ error: "Ungültige Herold-Aktion." }, 400);
  }

  try {
    const fundResponse = await fetch("https://raw.githubusercontent.com/agunz-png/rabenruf/main/herold-funde.json", {
      headers: { "Accept": "application/json" },
      signal: AbortSignal.timeout(12000),
    });
    if (!fundResponse.ok) throw new Error("Die aktuelle Herold-Liste konnte nicht geladen werden.");
    const funds = await fundResponse.json();
    const fund = Array.isArray(funds) ? funds.find((item: any) => String(item?.id || "") === eventId) : null;
    if (!fund) return reply({ error: "Dieser Fund ist nicht mehr in der Herold-Liste." }, 404);

    let event = null;
    if (action === "approve") {
      const name = String(fund.name || "").trim();
      const city = String(fund.city || "").trim();
      const country = String(fund.country || "").trim();
      const dateText = String(fund.date || "").trim();
      if (!name || !city || !country) return reply({ error: "Name, Ort oder Land fehlt." }, 422);
      const { start, end } = parseDates(dateText, fund);
      let coordinates: { lat: number; lng: number } | null = null;
      let nominatimStatus = 0;
      try {
        const query = new URLSearchParams({ city, country, format: "jsonv2", limit: "1" });
        const geoResponse = await fetch("https://nominatim.openstreetmap.org/search?" + query, {
          headers: { "User-Agent": "Rabenruf/1.0 (https://github.com/agunz-png/rabenruf)" },
          signal: AbortSignal.timeout(12000),
        });
        nominatimStatus = geoResponse.status;
        if (geoResponse.ok) {
          const locations = await geoResponse.json();
          if (Array.isArray(locations) && locations.length) {
            const lat = Number(locations[0].lat);
            const lng = Number(locations[0].lon);
            if (Number.isFinite(lat) && Number.isFinite(lng)) coordinates = { lat, lng };
          }
        } else {
          console.warn("Nominatim returned HTTP", geoResponse.status);
        }
      } catch (geoError) {
        console.warn("Nominatim request failed:", geoError);
      }

      if (!coordinates) {
        try {
          const photonQuery = new URLSearchParams({ q: city + ", " + country, limit: "1" });
          const photonResponse = await fetch("https://photon.komoot.io/api/?" + photonQuery, {
            headers: { "User-Agent": "Rabenruf/1.0 (https://github.com/agunz-png/rabenruf)" },
            signal: AbortSignal.timeout(12000),
          });
          if (!photonResponse.ok) {
            console.error("Photon returned HTTP", photonResponse.status);
            return reply({ error: "Die Karten-Ortsprüfung ist gerade nicht erreichbar. Bitte in einer Minute erneut versuchen." }, 503);
          }
          const photonData = await photonResponse.json();
          const point = photonData?.features?.[0]?.geometry?.coordinates;
          if (Array.isArray(point) && point.length >= 2) {
            const lng = Number(point[0]);
            const lat = Number(point[1]);
            if (Number.isFinite(lat) && Number.isFinite(lng)) coordinates = { lat, lng };
          }
        } catch (photonError) {
          console.error("Photon geocoding failed:", photonError, "Nominatim status:", nominatimStatus);
          return reply({ error: "Die Karten-Ortsprüfung ist gerade nicht erreichbar. Bitte in einer Minute erneut versuchen." }, 503);
        }
      }
      if (!coordinates) return reply({ error: "Für diesen Ort wurden keine Kartenkoordinaten gefunden. Prüfe Ort und Land." }, 422);
      const type = String(fund.type || "Markt");
      event = {
        id: "herold-" + eventId,
        name,
        type,
        tags: type === "Buhurt" ? ["Buhurt", "Turnier", "Herold"] : ["Mittelalter", "Herold"],
        start,
        end,
        date: dateText || (start === end ? start : start + " bis " + end),
        country,
        flag: flags[country] || "🏰",
        city,
        venue: "",
        address: city + ", " + country,
        lat: coordinates.lat,
        lng: coordinates.lng,
        website: String(fund.website || fund.organizer_url || fund.organizerUrl || "").trim(),
        source: String(fund.source || "").trim(),
        organizer: String(fund.organizer || "").trim(),
        info: "Gefunden und bestätigt durch den Herold",
        hours: "",
      };
    }

    const adminClient = createClient(url, serviceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    const { error } = await adminClient.from("herold_decisions").upsert({
      event_id: eventId,
      status: action === "approve" ? "approved" : "rejected",
      event,
      updated_at: new Date().toISOString(),
    }, { onConflict: "event_id" });
    if (error) throw error;
    return reply({ ok: true, action, event_id: eventId, event });
  } catch (error) {
    console.error("Herold-Aktion fehlgeschlagen:", error);
    return reply({ error: error instanceof Error ? error.message : "Herold-Aktion fehlgeschlagen." }, 500);
  }
});