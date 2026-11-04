# Technical documentation

BetterOption is a discontinued job-search POC/MVP. Start with the implemented
system and its local evaluation path:

| Guide | Contents |
| --- | --- |
| [Architecture](architecture.md) | Components, data flow, persistence, workers, and trade-offs |
| [Local development](local-development.md) | Python 3.12 setup, configuration, tests, and source packaging |
| [UI walkthrough](ui-walkthrough.md) | Screens, routes, user actions, and source templates |
| [Provider integration](provider-integration.md) | Optional adapters, evidence boundaries, and budget controls |

The [root README](../README.md) is the portfolio entry point. Source code,
schemas, templates, and regression tests remain the implementation reference;
older design notes can describe behavior that later changed.

## Historical context

[Engineering history](archive/engineering-history/README.md) contains versioned
architecture notes, release notes, local guides, provider reviews, and deployment
experiments. The [early profile protocol](archive/engineering-history/design/profile-protocol-v0.1.md)
and [job corpus design](archive/engineering-history/design/job-corpus-v0.1.md)
explain the origins of the evidence model.

[Discontinued product planning](archive/discontinued-product-planning/README.md)
contains former business, pricing, naming, launch, and compliance drafts.
These are historical planning material, with no active launch or commercial
commitment.
