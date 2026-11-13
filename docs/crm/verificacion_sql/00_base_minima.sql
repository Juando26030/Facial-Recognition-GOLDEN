-- Base mínima que imita lo que la migración 0130 necesita de las tablas existentes (tenants, staff_users, events). SOLO para la verificación con psql; no es una migración.
CREATE TABLE tenants (id text PRIMARY KEY, client_code text NOT NULL UNIQUE, name text NOT NULL);
CREATE TABLE staff_users (id serial PRIMARY KEY, username text UNIQUE NOT NULL);
CREATE TABLE events (id serial PRIMARY KEY, tenant_id text NOT NULL REFERENCES tenants(id), event_code text NOT NULL UNIQUE, name text NOT NULL);
