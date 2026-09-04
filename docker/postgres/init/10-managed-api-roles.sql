-- The roles a managed PostgreSQL host places in front of its automatic REST layer.
--
-- This is host provisioning, not schema. It runs once from the image's `initdb` hook, before
-- any migration, exactly as those roles exist before our migrations on the hosted developer
-- database -- and it is the smallest thing that makes a vanilla PostgreSQL container able to
-- prove a security property the deployed database has to keep.
--
-- Without it, `REVOKE_API_ROLES` in migration 0002 is a branch that only ever executes on the
-- managed host, and `test_no_managed_api_role_can_reach_the_private_schema` cannot run at all:
-- the test refuses to pass vacuously, and says so. With it, every local and CI run exercises
-- the revocation and asserts the outcome.
--
-- These are the roles and nothing else. It is deliberately not an emulation of a managed
-- platform: no API gateway, no auth schema, no storage, no publication. Three login-less
-- roles, so that "our schema is unreachable from the REST layer" is a claim something checks.

DO $$
DECLARE
    api_role text;
BEGIN
    FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOINHERIT', api_role);
        END IF;
    END LOOP;
END
$$;
