import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const allowedOrigin = (origin: string | null) => Boolean(origin && (
  origin === "https://agunz-png.github.io" ||
  origin === "https://rabenruf-test.vercel.app" ||
  origin === "https://rabenruf.ch" ||
  origin === "https://www.rabenruf.ch"
));
const ADMIN_EMAIL = "agunz@bluewin.ch";
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
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
  if (!allowedOrigin(origin)) return reply({ error: "Diese Herkunft ist nicht zugelassen." }, 403);

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

  let payload: { action?: string; event_id?: string; approved_event_id?: string; overrides?: Record<string, unknown> };
  try { payload = await req.json(); } catch { return reply({ error: "Ungültige Anfrage." }, 400); }
  const action = payload.action;
  const eventId = String(payload.event_id || "").trim();
  if (!["approve", "reject", "duplicate", "date_change"].includes(action || "") || !/^[A-Za-z0-9_-]{1,120}$/.test(eventId)) {
    return reply({ error: "Ungültige Herold-Aktion." }, 400);
  }

  try {
    const adminClient = createClient(url, serviceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    if (action === "duplicate" || action === "date_change") {
      const targetId = String(payload.approved_event_id || "").trim();
      if (!/^[A-Za-z0-9_-]{1,120}$/.test(targetId) || targetId === eventId) {
        return reply({ error: "Ungültige Zielveranstaltung." }, 400);
      }
      const { data: target, error: targetError } = await adminClient.from("herold_decisions")
        .select("event_id,status,event").eq("event_id", targetId).maybeSingle();
      if (targetError) throw targetError;
      if (!target || target.status !== "approved" || !target.event) {
        return reply({ error: "Die Zielveranstaltung ist nicht bestätigt." }, 422);
      }
      const fundResponse = await fetch("https://raw.githubusercontent.com/agunz-png/rabenruf/main/herold-funde.json", {
        headers: { "Accept": "application/json" },
        signal: AbortSignal.timeout(12000),
      });
      if (!fundResponse.ok) return reply({ error: "Herold-Funde können nicht geprüft werden." }, 503);
      const funds = await fundResponse.json();
      const fund = Array.isArray(funds) ? funds.find((item: Record<string, unknown>) => String(item.id || "") === eventId) : null;
      if (!fund) return reply({ error: "Fund nicht mehr in der aktuellen Herold-Liste. Bitte neu laden." }, 409);
      const canonical = (value: unknown) => String(value || "").normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().replace(/\s+/g, " ");
      const city = (value: unknown) => canonical(value).replace(/\b(?:ag|ai|ar|be|bl|bs|fr|ge|gl|gr|ju|lu|ne|nw|ow|sg|sh|so|sz|tg|ti|ur|vd|vs|zg|zh)$/, "").trim();
      const title = (value: unknown) => canonical(String(value || "").replace(/&#(?:0*38|x0*26);|&amp;/gi, "&"))
        .replace(/\b(?:geplant|mps|mittelalterliches|mittelalterlich)\b/g, "").trim();
      const approved = target.event as Record<string, unknown>;
      const sameDates = String(fund.start || "") === String(approved.start || "") &&
        String(fund.end || fund.start || "") === String(approved.end || approved.start || "");
      const samePlace = Boolean(city(fund.city) && city(approved.city) &&
        (city(fund.city) === city(approved.city) ||
          city(fund.city).includes(city(approved.city)) ||
          city(approved.city).includes(city(fund.city))));
      const sameCountry = Boolean(canonical(fund.country) && canonical(fund.country) === canonical(approved.country));
      const fundTitle = title(fund.name);
      const approvedTitle = title(approved.name);
      // Source may say "Mittelaltermarkt" while approved event adds the exact city.
      // Require strict matching of both dates, city and country as well.
      const genericMarketAlias = fundTitle === "mittelaltermarkt" &&
        approvedTitle === "mittelaltermarkt " + city(fund.city);
      const editionAlias = fundTitle.length >= 16 &&
        approvedTitle.startsWith(fundTitle + " ") &&
        /^20\d{2}(?:\s|$)/.test(approvedTitle.slice(fundTitle.length).trim());
      const subtitleAlias = fundTitle.length >= 16 && approvedTitle.length >= 16 &&
        (fundTitle.startsWith(approvedTitle + " ") || approvedTitle.startsWith(fundTitle + " "));
      const sameTitle = Boolean(fundTitle && (fundTitle === approvedTitle ||
        ((genericMarketAlias || editionAlias || subtitleAlias) && sameDates && samePlace && sameCountry)));
      const changeAllowed = action === "date_change" && !sameDates && samePlace && sameCountry &&
        fundTitle.length >= 15 && fundTitle === approvedTitle &&
        String(fund.start || "").slice(0,4) === String(approved.start || "").slice(0,4) &&
        /^20\d{2}-\d{2}-\d{2}$/.test(String(fund.start||"")) &&
        /^20\d{2}-\d{2}-\d{2}$/.test(String(fund.end||"")) &&
        String(fund.end)>=String(fund.start) &&
        Math.abs(Date.parse(String(fund.start))-Date.parse(String(approved.start))) <= 31*86400000;
      if (!(sameDates && samePlace && sameCountry && sameTitle) && !changeAllowed) {
        const differences: string[] = [];
        if (!sameTitle) differences.push("Name: Herold „" + String(fund.name || "–") + "“, Kalender „" + String(approved.name || "–") + "“");
        if (!samePlace) differences.push("Ort: Herold „" + String(fund.city || "–") + "“, Kalender „" + String(approved.city || "–") + "“");
        if (!sameCountry) differences.push("Land: Herold „" + String(fund.country || "–") + "“, Kalender „" + String(approved.country || "–") + "“");
        if (!sameDates) differences.push("Zeitraum: Herold " + String(fund.start || "–") + " bis " + String(fund.end || fund.start || "–") +
          ", Kalender " + String(approved.start || "–") + " bis " + String(approved.end || approved.start || "–"));
        return reply({
          error: "Verknüpfung abgelehnt. Unterschiedliche Angaben:\n" + differences.join("\n") +
            "\nBitte den richtigen Kalendereintrag auswählen oder den Fund separat prüfen.",
          code: "DUPLICATE_MISMATCH",
          differences,
        }, 422);
      }
      if(action === "date_change"){
        if(!changeAllowed)return reply({error:"Kein eindeutig belegbarer Datumswechsel."},422);
        const newStart=String(fund.start),newEnd=String(fund.end||fund.start);
        const oldHours=Array.isArray(approved.dailyHours)?approved.dailyHours:[];
        const dailyHours=oldHours.filter((day:any)=>day && String(day.date)>=newStart && String(day.date)<=newEnd);
        const updatedEvent={...approved,start:newStart,end:newEnd,
          date:newStart===newEnd?newStart:newStart+" bis "+newEnd,
          dailyHours,hours:dailyHours.length?String(approved.hours||""):"",
          info:String(approved.info||"").slice(0,1200)};
        const {error:updateError}=await adminClient.from("herold_decisions")
          .update({event:updatedEvent,updated_at:new Date().toISOString()})
          .eq("event_id",targetId).eq("status","approved");
        if(updateError)throw updateError;
      }
      const { error: linkError } = await adminClient.from("herold_duplicate_links")
        .upsert({ candidate_id: eventId, approved_event_id: targetId }, { onConflict: "candidate_id" });
      if (linkError) throw linkError;
      return reply({ ok: true, action, event_id: eventId, approved_event_id: targetId });
    }
    if (action === "approve") {
      const { data: priorDecision, error: priorDecisionError } = await adminClient.from("herold_decisions")
        .select("status").eq("event_id", eventId).maybeSingle();
      if (priorDecisionError) throw priorDecisionError;
      if (priorDecision?.status === "rejected") {
        return reply({ error: "Dieser Fund wurde dauerhaft gelöscht und kann nicht mehr freigegeben werden." }, 409);
      }
    }

    const fundResponse = await fetch("https://raw.githubusercontent.com/agunz-png/rabenruf/main/herold-funde.json", {
      headers: { "Accept": "application/json" },
      signal: AbortSignal.timeout(12000),
    });
    if (!fundResponse.ok) throw new Error("Die aktuelle Herold-Liste konnte nicht geladen werden.");
    const funds = await fundResponse.json();
    const fund = Array.isArray(funds) ? funds.find((item: any) => String(item?.id || "") === eventId) : null;
    if (!fund) return reply({ error: "Dieser Fund ist nicht mehr in der Herold-Liste." }, 404);

    let event = null;
    let locationWarning: string | undefined;
    if (action === "approve") {
      const overrides = payload.overrides && typeof payload.overrides === "object" ? payload.overrides : {};
      const readOverride = (key: string, fallback: unknown, max: number) =>
        String(overrides[key] ?? fallback ?? "").trim().slice(0, max);
      const name = readOverride("name", fund.name, 180);
      const city = readOverride("city", fund.city, 100);
      const country = readOverride("country", fund.country, 100);
      const startOverride = readOverride("start", fund.start, 10);
      const endOverride = readOverride("end", fund.end || startOverride, 10);
      const dateText = startOverride && /^20\d{2}-\d{2}-\d{2}$/.test(startOverride)
        ? (endOverride && endOverride !== startOverride ? startOverride + " bis " + endOverride : startOverride)
        : readOverride("date", fund.date, 100);
      const type = readOverride("type", fund.type || "Markt", 40);
      const allowedTypes = new Set(["Markt","MPS","Lager","Reenactment","Buhurt","Spezialevent"]);
      const tags = Array.isArray(overrides.tags)
        ? overrides.tags.map(value => String(value)).filter(value => allowedTypes.has(value)).slice(0, 6)
        : (Array.isArray(fund.tags) ? fund.tags.filter((value: unknown) => allowedTypes.has(String(value))) : []);
      if (!allowedTypes.has(type) || !tags.length) return reply({ error: "Bitte wähle mindestens eine gültige Veranstaltungskategorie." }, 422);
      if (!name || !city || !country) return reply({ error: "Name, Ort oder Land fehlt." }, 422);
      const { start, end } = parseDates(dateText, { start: startOverride, end: endOverride });
      const suppliedLat = Number(fund.lat);
      const suppliedLng = Number(fund.lng);
      let coordinates: { lat: number; lng: number } | null =
        Number.isFinite(suppliedLat) && Number.isFinite(suppliedLng) &&
        Math.abs(suppliedLat) <= 90 && Math.abs(suppliedLng) <= 180 &&
        !(suppliedLat === 0 && suppliedLng === 0)
          ? { lat: suppliedLat, lng: suppliedLng }
          : null;
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
            console.error("Photon returned HTTP", photonResponse.status);
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
          console.error("Photon geocoding failed:", photonError, "Nominatim status:", nominatimStatus);
        }
      }
      if (!coordinates) {
        locationWarning = "Übernommen, aber die Kartendienste sind derzeit nicht erreichbar. Der Termin erscheint im Kalender; der Kartenpunkt wird ergänzt, sobald Koordinaten verfügbar sind.";
        console.warn("Approving event without coordinates because geocoding providers are unavailable.");
      }
      event = {
        id: "herold-" + eventId,
        name,
        type,
        tags: [...tags, "Herold"],
        start,
        end,
        date: dateText || (start === end ? start : start + " bis " + end),
        country,
        flag: flags[country] || "🏰",
        city,
        venue: readOverride("venue", fund.venue, 180),
        address: readOverride("address", fund.address || (city + ", " + country), 240),
        lat: coordinates?.lat ?? null,
        lng: coordinates?.lng ?? null,
        website: readOverride("website", fund.website || fund.organizer_url || fund.organizerUrl, 500),
        source: String(fund.source || "").trim(),
        organizer: readOverride("organizer", fund.organizer, 180),
        info: readOverride("info", fund.info || "Gefunden und bestätigt durch den Herold", 2000),
        hours: readOverride("hours", fund.hours, 180),
        dailyHours: (() => {
          const proposed = payload.overrides?.dailyHours;
          if (!Array.isArray(proposed)) return [];
          if (proposed.length > 8) throw new Error("Zu viele Tageszeiten.");
          const seen = new Set<string>();
          return proposed.map((item: any) => {
            const day = String(item?.date || "");
            const open = String(item?.open || "");
            const close = String(item?.close || "");
            if (!/^20\d{2}-\d{2}-\d{2}$/.test(day) ||
                !/^(?:[01]\\d|2[0-3]):[0-5]\\d$/.test(open) ||
                !/^(?:[01]\\d|2[0-3]):[0-5]\\d$/.test(close) ||
                day < start || day > end || open >= close || seen.has(day)) {
              throw new Error("Ungültige oder doppelte Tageszeit.");
            }
            seen.add(day);
            return { date: day, open, close };
          });
        })(),
        flyer: readOverride("flyer", fund.flyer, 1000),
      };
    }

    const { error } = await adminClient.from("herold_decisions").upsert({
      event_id: eventId,
      status: action === "approve" ? "approved" : "rejected",
      event,
      updated_at: new Date().toISOString(),
    }, { onConflict: "event_id" });
    if (error) throw error;
    return reply({ ok: true, action, event_id: eventId, event, ...(typeof locationWarning !== "undefined" && locationWarning ? { warning: locationWarning } : {}) });
  } catch (error) {
    console.error("Herold-Aktion fehlgeschlagen:", error);
    return reply({ error: error instanceof Error ? error.message : "Herold-Aktion fehlgeschlagen." }, 500);
  }
});