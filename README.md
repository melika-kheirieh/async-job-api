Day 1 Notes

What I built:
- A FastAPI API with POST /jobs and GET /jobs/{job_id}
- A SQLAlchemy Job model
- DB-backed job creation with queued status
- A repository/service boundary
- Basic 404 handling for missing jobs

What I learned:
- SQLAlchemy is the bridge between Python code and the database.
- The engine stores database connection configuration.
- A Session is the active working context for DB operations.
- add prepares an object for persistence.
- commit writes changes to the database.
- refresh reloads the final DB state into the Python object.
- Pydantic schemas define the API contract.
- SQLAlchemy models define the database shape.

Main confusion resolved:
- commit writes; refresh reads back.
- service means use-case/business logic layer, not microservice.
- create_all is a temporary learning/prototype substitute for migrations, not production migration management.

Tomorrow I need:
- Make the service layer own job lifecycle transitions more explicitly.
- Add cleaner transaction/status methods like mark_running, mark_completed, and mark_failed.

1. Why do we use refresh(job) after commit?
After commit, the row is persisted in the database. refresh(job) reloads the latest database state into the Python object, including DB-generated values like id, timestamps, or defaults.


2. What is the route responsible for?
The route is responsible for HTTP concerns: receiving the request, validating input through schemas, calling the service, returning the response, and raising HTTP errors like 404.

3. What does the repository hide from the route?
The repository hides database access details: creating SQLAlchemy objects, add, commit, refresh, and query logic. The route does not need to know how data is persisted.

4. Why 201 Created instead of 202 Accepted for now?
Because POST /jobs currently creates a job resource immediately in the database. 202 Accepted becomes more appropriate later when the request starts an async workflow and the actual processing happens in the background.