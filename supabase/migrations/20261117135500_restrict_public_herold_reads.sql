-- Replace the previous unrestricted read policies with the narrower policies
-- defined in 20261117124500_herold_read_policies.sql.
DROP POLICY IF EXISTS "Public can read Herold decisions"
ON public.herold_decisions;

DROP POLICY IF EXISTS "Read duplicate mappings"
ON public.herold_duplicate_links;
