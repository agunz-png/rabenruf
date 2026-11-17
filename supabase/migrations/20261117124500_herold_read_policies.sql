-- Public calendar clients may read approved event payloads.
-- The Herold admin may read all decisions and duplicate links using its auth JWT.
CREATE POLICY "Public can read approved Herold events"
ON public.herold_decisions
FOR SELECT
TO anon, authenticated
USING (status = 'approved' AND event IS NOT NULL);

CREATE POLICY "Herold admin can read all decisions"
ON public.herold_decisions
FOR SELECT
TO authenticated
USING (
  lower(coalesce(auth.jwt() ->> 'email', '')) = 'agunz@bluewin.ch'
);

CREATE POLICY "Herold admin can read duplicate links"
ON public.herold_duplicate_links
FOR SELECT
TO authenticated
USING (
  lower(coalesce(auth.jwt() ->> 'email', '')) = 'agunz@bluewin.ch'
);
