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
const types = new Set(["Markt", "MPS", "Lager", "Reenactment", "Buhurt", "Spezialevent"]);

function reply(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}
function validIsoDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^20\d{2}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(value + "T00:00:00Z");
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}
function cleanText(value: unknown, max: number): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}
function safeUrl(value: unknown, max = 500): string {
  const text = cleanText(value, max);
  if (!text) return "";
  try {
    const url = new URL(text);
    return ["https:", "http:"].includes(url.protocol) ? url.toString() : "";
  } catch { return ""; }
}
function dateLabel(start: string, end: string): string {
  const fmt = (value: string, options: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat("de-CH", { ...options, timeZone: "UTC" })
      .format(new Date(value + "T12:00:00Z"));
  const a = new Date(start + "T12:00:00Z");
  const b = new Date(end + "T12:00:00Z");
  if (start === end) return fmt(start, { day: "numeric", month: "long", year: "numeric" });
  if (a.getUTCFullYear() === b.getUTCFullYear() && a.getUTCMonth() === b.getUTCMonth()) {
    return fmt(start, { day: "numeric" }) + ".–" +
      fmt(end, { day: "numeric", month: "long", year: "numeric" });
  }
  return fmt(start, { day: "numeric", month: "long", year: "numeric" }) + " bis " +
    fmt(end, { day: "numeric", month: "long", year: "numeric" });
}
function validEvent(value: unknown, eventId: string): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const name = cleanText(raw.name, 180);
  const type = cleanText(raw.type, 30);
  const city = cleanText(raw.city, 100);
  const country = cleanText(raw.country, 100);
  const start = raw.start;
  const end = raw.end;
  const lat = Number(raw.lat);
  const lng = Number(raw.lng);
  if (raw.id !== eventId || !name || !types.has(type) || !city || !country ||
      !validIsoDate(start) || !validIsoDate(end) || end < start ||
      !Number.isFinite(lat) || lat < -90 || lat > 90 ||
      !Number.isFinite(lng) || lng < -180 || lng > 180) return null;
  const tags = Array.isArray(raw.tags)
    ? raw.tags.filter((tag): tag is string => typeof tag === "string").slice(0, 8).map(tag => cleanText(tag, 40))
    : [];
  return {
    id: eventId,
    name, type, tags, start, end,
    date: dateLabel(start, end),
    country, flag: flags[country] || "🏰", city,
    venue: cleanText(raw.venue, 180),
    address: cleanText(raw.address, 240) || city + ", " + country,
    lat, lng,
    website: safeUrl(raw.website),
    flyer: safeUrl(raw.flyer, 1000),
    source: safeUrl(raw.source),
    organizer: cleanText(raw.organizer, 160),
    info: cleanText(raw.info, 1200),
    hours: cleanText(raw.hours, 240),
  };
}
async function coordinatesFor(city: string, country: string): Promise<{lat:number;lng:number}|null> {
  const query = new URLSearchParams({ city, country, format: "jsonv2", limit: "1" });
  try {
    const response = await fetch("https://nominatim.openstreetmap.org/search?" + query, {
      headers: { "User-Agent": "Rabenruf/1.0 (https://github.com/agunz-png/rabenruf)" },
      signal: AbortSignal.timeout(12000),
    });
    if (response.ok) {
      const data = await response.json();
      if (Array.isArray(data) && data[0]) {
        const lat = Number(data[0].lat), lng = Number(data[0].lon);
        if (Number.isFinite(lat) && Number.isFinite(lng)) return { lat, lng };
      }
    }
  } catch (error) { console.warn("Nominatim failed", error); }
  try {
    const photonQuery = new URLSearchParams({ q: city + ", " + country, limit: "1" });
    const response = await fetch("https://photon.komoot.io/api/?" + photonQuery, {
      headers: { "User-Agent": "Rabenruf/1.0 (https://github.com/agunz-png/rabenruf)" },
      signal: AbortSignal.timeout(12000),
    });
    if (!response.ok) return null;
    const data = await response.json();
    const point = data?.features?.[0]?.geometry?.coordinates;
    if (Array.isArray(point) && point.length >= 2) {
      const lng = Number(point[0]), lat = Number(point[1]);
      if (Number.isFinite(lat) && Number.isFinite(lng)) return { lat, lng };
    }
  } catch (error) { console.warn("Photon failed", error); }
  return null;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return reply({ error: "Methode nicht erlaubt." }, 405);
  if (req.headers.get("Origin") !== APP_ORIGIN) return reply({ error: "Diese Herkunft ist nicht zugelassen." }, 403);

  const authHeader = req.headers.get("Authorization");
  const token = authHeader?.replace(/^Bearer\s+/i, "");
  const url = Deno.env.get("SUPABASE_URL");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!token || !url || !anonKey || !serviceKey) return reply({ error: "Bitte melde dich mit dem Herold-Passwort an." }, 401);

  const authClient = createClient(url, anonKey, {
    auth: { persistSession: false, autoRefreshToken: false },
    global: { headers: { Authorization: authHeader! } },
  });
  const { data: { user }, error: authError } = await authClient.auth.getUser(token);
  if (authError || !user || user.email?.toLowerCase() !== ADMIN_EMAIL || !user.email_confirmed_at) {
    return reply({ error: "Diese Funktion ist nur mit dem bestätigten Herold-Konto zugänglich." }, 403);
  }

  const admin = createClient(url, serviceKey, { auth: { persistSession: false, autoRefreshToken: false } });
  let payload: Record<string, unknown>;
  try {
    const parsed = await req.json();
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return reply({ error: "Ungültige Anfrage." }, 400);
    payload = parsed as Record<string, unknown>;
  } catch { return reply({ error: "Ungültige Anfrage." }, 400); }

  try {
    if (payload.action === "list") {
      const { data, error } = await admin.from("herold_update_requests")
        .select("id,event_id,old_event,proposed_event,created_at")
        .eq("status", "pending").order("created_at", { ascending: true }).limit(100);
      if (error) throw error;
      return reply({ ok: true, updates: data || [] });
    }

    if (payload.action === "submit") {
      const eventId = cleanText(payload.event_id, 120);
      if (!/^[A-Za-z0-9_-]{1,120}$/.test(eventId)) return reply({ error: "Ungültige Termin-ID." }, 400);
      const eventIds = new Set([eventId]);
      if (eventId.startsWith("herold-") && eventId.length > "herold-".length) {
        eventIds.add(eventId.slice("herold-".length));
      }
      const { data: priorDecision, error: priorDecisionError } = await admin.from("herold_decisions")
        .select("status").in("event_id", [...eventIds]).eq("status", "rejected").limit(1).maybeSingle();
      if (priorDecisionError) throw priorDecisionError;
      if (priorDecision?.status === "rejected") return reply({ error: "Dieser Termin wurde dauerhaft gelöscht und kann nicht mehr geändert werden." }, 410);
      const oldEvent = validEvent(payload.old_event, eventId);
      const proposed = validEvent(payload.proposed_event, eventId);
      if (!oldEvent || !proposed) return reply({ error: "Bitte prüfe die Pflichtfelder: Titel, Zeitraum, Ort und Land." }, 422);
      if (proposed.city !== oldEvent.city || proposed.country !== oldEvent.country) {
        const coordinates = await coordinatesFor(String(proposed.city), String(proposed.country));
        if (!coordinates) return reply({ error: "Für den geänderten Ort konnten keine Kartenkoordinaten gefunden werden." }, 422);
        proposed.lat = coordinates.lat;
        proposed.lng = coordinates.lng;
      }
      const { data, error } = await admin.from("herold_update_requests")
        .insert({ event_id: eventId, old_event: oldEvent, proposed_event: proposed, status: "pending" })
        .select("id").single();
      if (error) {
        if (error.code === "23505") return reply({ error: "Für diesen Termin gibt es bereits eine Änderung zur Prüfung." }, 409);
        throw error;
      }
      return reply({ ok: true, request_id: data.id });
    }

    if (payload.action === "delete") {
      const eventId = cleanText(payload.event_id, 120);
      if (!/^[A-Za-z0-9_-]{1,120}$/.test(eventId)) return reply({ error: "Ungültige Termin-ID." }, 400);
      const eventIds = new Set([eventId]);
      if (eventId.startsWith("herold-") && eventId.length > "herold-".length) {
        eventIds.add(eventId.slice("herold-".length));
      }
      const updatedAt = new Date().toISOString();
      const { error: decisionError } = await admin.from("herold_decisions").upsert(
        [...eventIds].map(id => ({ event_id: id, status: "rejected", event: null, updated_at: updatedAt })),
        { onConflict: "event_id" },
      );
      if (decisionError) throw decisionError;
      const { error: updateError } = await admin.from("herold_update_requests")
        .update({ status: "rejected", updated_at: updatedAt })
        .in("event_id", [...eventIds]).eq("status", "pending");
      if (updateError) throw updateError;
      return reply({ ok: true, action: "delete", event_id: eventId });
    }

    if (payload.action === "approve" || payload.action === "reject") {
      const requestId = cleanText(payload.request_id, 80);
      if (!/^[0-9a-f-]{36}$/i.test(requestId)) return reply({ error: "Ungültige Änderungs-ID." }, 400);
      const { data: request, error: readError } = await admin.from("herold_update_requests")
        .select("id,event_id,proposed_event,status").eq("id", requestId).maybeSingle();
      if (readError) throw readError;
      if (!request || request.status !== "pending") return reply({ error: "Dieser Vorschlag ist nicht mehr offen." }, 404);

      if (payload.action === "approve") {
        const event = validEvent(request.proposed_event, request.event_id);
        if (!event) return reply({ error: "Der gespeicherte Änderungsvorschlag ist ungültig." }, 422);
        const { error } = await admin.from("herold_decisions").upsert({
          event_id: request.event_id, status: "approved", event, updated_at: new Date().toISOString(),
        }, { onConflict: "event_id" });
        if (error) throw error;
      }
      const status = payload.action === "approve" ? "approved" : "rejected";
      const { error: updateError } = await admin.from("herold_update_requests")
        .update({ status, updated_at: new Date().toISOString() })
        .eq("id", requestId).eq("status", "pending");
      if (updateError) throw updateError;
      return reply({ ok: true, action: payload.action, event_id: request.event_id });
    }
    return reply({ error: "Unbekannte Aktion." }, 400);
  } catch (error) {
    console.error("Herold-Terminänderung fehlgeschlagen:", error);
    return reply({ error: error instanceof Error ? error.message : "Die Anfrage ist fehlgeschlagen." }, 500);
  }
});
