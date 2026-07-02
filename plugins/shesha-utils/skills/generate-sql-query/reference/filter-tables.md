<tables>
These available database tables:
{tables}
</tables>

<instructions>
Which tables are most likely relevant to answer this query?
Return only the table id's as a JSON array, maximum 5 tables.
If the question does not seem related to the database, just return empty valid JSON array.
</instructions>

<information>
Consider table name patterns:
- Abp* = Framework tables (users, roles, permissions, tenants)
- Core_* = Core system tables (persons[users], organisations, areas, facilities)
- entpr_* = Enterprise tables (checklists, invoices, orders, products)
- Disp_* = Dispatch/Emergency tables (incidents, vehicles, assignments)
- DEP_* = Department tables (events, contacts, notifications)
- SM_* = Service Management tables (cases, articles, case types)
- chat_* = Chat/messaging tables
- asset_* = Asset management tables
- PEP_* = Emergency/Paramedic tables
- Frwk_* = Framework configuration tables
- ServiceAutomation_* = Service automation tables
- Botsa_* = Botsa related tables
</information>

<output>
Return ONLY a valid JSON array of table ID's nothing else.
</output>
