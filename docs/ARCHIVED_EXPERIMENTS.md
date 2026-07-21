# Archived experiments

Emvera's early development included several branches that explored a native mobile client, social features, paper-trading flows, analytics, promotions, support tickets, and real-money contest concepts.

Those experiments are intentionally not part of the sandbox release. Some depended on unfinished schemas or changed the product's legal and security boundary. They were preserved in an offline Git bundle before their remote branches were retired, so useful ideas can be recovered without implying that they are supported features.

The release branch remains focused on a smaller, verifiable product:

- server-rendered Django;
- synthetic data and Plaid Sandbox;
- no brokerage orders, payments, prizes, or real-money contests;
- explicit ownership, authentication, and deployment controls;
- repeatable tests and documentation.

Future work should be reintroduced as small reviewed changes against those boundaries, never by merging an experimental branch wholesale.
