Interior Design Agent

A tool-based AI agent that creates Living Room design plans based on room dimensions, budget, style preferences, and user constraints.

Live App: https://interior-design-agent-geetika.streamlit.app/

What it does

The agent:

Searches a structured furniture catalog
Selects products based on user requirements
Checks the total cost against the user's budget
Checks whether the furniture can fit in the room
Handles infeasible requests honestly
Refuses out-of-scope structural, electrical, and plumbing requests
How it works

The agent uses three tools:

Catalog Search — finds suitable products from the SQLite catalog
Budget Calculator — checks whether selected products stay within budget
Layout Fit Check — checks basic spatial feasibility

The agent then returns a structured outcome such as:

ok · infeasible_budget · infeasible_layout · unavailable_items · out_of_scope

Evaluation

The project includes a 25-case evaluation harness covering:

Real briefs and happy paths
Budget and layout edge cases
Catalog issues and out-of-stock items
Safety and out-of-scope requests
Input validation
Product selection quality

Evaluation combines deterministic checks with an LLM-as-a-judge.
