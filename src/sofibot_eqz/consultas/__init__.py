"""Functionality 2, data queries (docs/11-consultas.md).

A separate service (`sofibot serve-consultas`, the `consultas` container) with its own
settings, its own SQL Server login and its own record. Users (or, later, an AI agent acting
for them) ask for measures by dimensions from a semantic catalog (reports/catalogo.json);
the service checks their Entra roles and Gold tables, builds the SQL itself with parameters,
runs it with limits and records who asked what. It never accepts SQL.

It shares only the sign-in and the table permissions with the rest of Sofibot
(identity.py, access.py): no code path of functionality 1 reaches data through here.
"""
