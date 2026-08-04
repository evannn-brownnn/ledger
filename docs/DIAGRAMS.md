# Architecture diagrams

Mermaid source. Renders natively on GitHub and in VS Code with the Markdown
Preview Mermaid extension.

Pre-rendered PNGs of every diagram are in `docs/diagrams/` if you want to
drop one into a slide or a README without a renderer.

To re-render after editing:

```bash
npm install -g @mermaid-js/mermaid-cli
mmdc -i docs/DIAGRAMS.md -o docs/diagrams/out.md   # or per-diagram, see below
```

---

## 1 · Layering

Dependencies point one way only. The arrow direction is the whole rule: if
you ever find `app/domain` importing from `app/api`, something has gone
wrong.

```mermaid
flowchart TD
    Client([HTTP client])

    subgraph API["app/api — knows HTTP, not ledger rules"]
        Routes["v1/ledger.py<br/>routes"]
        Schemas["schemas.py<br/>pydantic validation"]
        Errors["errors.py<br/>exception → status code"]
        Deps["deps.py<br/>session, idempotency key,<br/>body fingerprint"]
    end

    subgraph DOMAIN["app/domain — knows ledger rules, not HTTP"]
        Ledger["ledger.py<br/>post, reverse, balance"]
        DErrors["errors.py<br/>domain exceptions"]
    end

    subgraph MODELS["app/models — tables and constraints"]
        Tables["Account, Transaction,<br/>TransactionLine,<br/>IdempotencyKey, AuditEvent"]
    end

    subgraph INFRA["infrastructure"]
        DB[("PostgreSQL<br/>CHECK · UNIQUE · FK")]
        Obs["observability.py<br/>logs · metrics · request id"]
    end

    Client -->|"JSON + Idempotency-Key"| Routes
    Errors -.->|"error envelope"| Client
    Routes --> Schemas
    Routes --> Deps
    Routes --> Ledger
    Ledger --> DErrors
    DErrors -.->|"raised, caught by"| Errors
    Ledger --> Tables
    Tables --> DB
    Routes -.-> Obs

    classDef api fill:#e8f0fe,stroke:#4285f4,color:#111
    classDef dom fill:#e6f4ea,stroke:#34a853,color:#111
    classDef mod fill:#fef7e0,stroke:#fbbc04,color:#111
    classDef inf fill:#f1f3f4,stroke:#5f6368,color:#111
    class Routes,Schemas,Errors,Deps api
    class Ledger,DErrors dom
    class Tables mod
    class DB,Obs inf
```

---

## 2 · Data model

Note what is absent: no `balance` column, no `status` column, no
`updated_at` anywhere. Those absences are the design.

```mermaid
erDiagram
    ACCOUNTS ||--o{ TRANSACTION_LINES : "is debited or credited by"
    TRANSACTIONS ||--|{ TRANSACTION_LINES : "consists of (2 or more)"
    TRANSACTIONS ||--o| IDEMPOTENCY_KEYS : "was created by"

    ACCOUNTS {
        uuid   id PK
        text   name UK
        text   normal_balance "CHECK debit|credit"
        char   currency "3 chars"
        ts     created_at
    }

    TRANSACTIONS {
        uuid   id PK
        text   memo
        char   currency
        uuid   reverses_id FK "UNIQUE — reverse once only"
        ts     created_at "indexed, partition key"
    }

    TRANSACTION_LINES {
        uuid    id PK
        uuid    transaction_id FK
        uuid    account_id FK
        text    direction "CHECK debit|credit"
        numeric amount "NUMERIC(20,4) CHECK > 0"
    }

    IDEMPOTENCY_KEYS {
        text   key PK "UNIQUE — the race arbiter"
        text   request_hash "sha256 of body"
        uuid   transaction_id FK
        ts     created_at
    }

    AUDIT_EVENTS {
        uuid   id PK
        text   actor
        text   action
        text   entity_type
        uuid   entity_id
        jsonb  payload
        ts     created_at
    }
```

### Why amounts are positive with a separate direction

```mermaid
flowchart LR
    subgraph BAD["signed amounts — rejected"]
        B1["amount: +100.00"]
        B2["amount: -100.00"]
        B3["negative amounts<br/>are representable<br/>→ bugs are possible"]
        B1 --- B2 --- B3
    end

    subgraph GOOD["positive + direction — chosen"]
        G1["amount: 100.00<br/>direction: debit"]
        G2["amount: 100.00<br/>direction: credit"]
        G3["CHECK amount > 0<br/>→ negatives are<br/>unrepresentable"]
        G1 --- G2 --- G3
    end

    classDef bad fill:#fce8e6,stroke:#d93025,color:#111
    classDef good fill:#e6f4ea,stroke:#34a853,color:#111
    class B1,B2,B3 bad
    class G1,G2,G3 good
```

---

## 3 · A posting, end to end

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant M as RequestContext<br/>middleware
    participant R as Route
    participant D as Domain
    participant PG as PostgreSQL

    C->>M: POST /transactions<br/>Idempotency-Key k1
    M->>M: assign request_id
    M->>R: forward
    R->>R: pydantic validates shape,<br/>types, pre-checks balance
    R->>R: sha256 of canonical body
    R->>PG: BEGIN ISOLATION LEVEL SERIALIZABLE

    R->>D: post_transaction(legs, key k1, hash h1)
    D->>PG: SELECT accounts WHERE id IN (...)
    PG-->>D: accounts
    D->>D: currency match, amounts positive,<br/>sum(debits) equals sum(credits)
    D->>PG: INSERT transaction
    D->>PG: INSERT transaction_lines
    D->>PG: SAVEPOINT → INSERT idempotency_key
    PG-->>D: ok
    D-->>R: Transaction

    R->>PG: COMMIT
    PG-->>R: committed
    R-->>M: 201 + TransactionOut
    M->>M: metrics + access log
    M-->>C: 201, X-Request-ID
```

---

## 4 · The race that matters

Two identical requests with the same idempotency key, arriving at the same
instant. This is the diagram to be able to draw on a whiteboard.

```mermaid
sequenceDiagram
    autonumber
    participant A as Request A
    participant B as Request B
    participant PG as PostgreSQL

    Note over A,B: both carry key k1

    par
        A->>PG: BEGIN
    and
        B->>PG: BEGIN
    end

    A->>PG: SELECT idempotency_keys WHERE key = k1
    PG-->>A: not found
    B->>PG: SELECT idempotency_keys WHERE key = k1
    PG-->>B: not found

    Note over A,B: both saw not found<br/>check-then-insert<br/>double-posts here

    A->>PG: INSERT txn + lines
    B->>PG: INSERT txn + lines

    A->>PG: SAVEPOINT → INSERT key k1
    PG-->>A: ok
    B->>PG: SAVEPOINT → INSERT key k1
    PG--xB: IntegrityError<br/>unique violation

    Note over B: the constraint arbitrates<br/>not application logic

    B->>PG: ROLLBACK TO SAVEPOINT
    B->>PG: SELECT idempotency_keys WHERE key = k1
    PG-->>B: transaction_id of A txn
    B->>PG: ROLLBACK and discard B txn

    A->>PG: COMMIT
    Note over A,B: one transaction exists<br/>both clients get the same id
```

---

## 5 · Isolation and retry

Why writes run at SERIALIZABLE, and what happens when Postgres aborts them.

```mermaid
flowchart TD
    Start([write request]) --> Begin["BEGIN ISOLATION LEVEL<br/>SERIALIZABLE"]
    Begin --> Work["domain logic:<br/>read state, decide, write"]
    Work --> Commit{COMMIT}

    Commit -->|success| Done([201 Created])
    Commit -->|"SQLSTATE 40001<br/>serialization failure"| Check{retries left?}
    Commit -->|"SQLSTATE 40P01<br/>deadlock"| Check
    Commit -->|other error| Fail([500 / domain error])

    Check -->|yes| Backoff["exponential backoff<br/>+ jitter"]
    Backoff --> Begin
    Check -->|no| Retry503(["503<br/>Retry-After: 1"])

    Note1["jitter is not decoration:<br/>without it, conflicting txns<br/>retry in lockstep and<br/>collide again"]
    Backoff -.- Note1

    classDef ok fill:#e6f4ea,stroke:#34a853,color:#111
    classDef warn fill:#fef7e0,stroke:#fbbc04,color:#111
    classDef bad fill:#fce8e6,stroke:#d93025,color:#111
    classDef note fill:#f1f3f4,stroke:#5f6368,color:#111,font-style:italic
    class Done ok
    class Check,Backoff,Retry503 warn
    class Fail bad
    class Note1 note
```

### The write skew this prevents

```mermaid
sequenceDiagram
    autonumber
    participant T1 as Withdrawal A
    participant T2 as Withdrawal B
    participant PG as PostgreSQL

    Note over T1,T2: balance is 100.00 and each<br/>wants to withdraw 100.00

    rect rgb(252, 232, 230)
        Note over T1,PG: READ COMMITTED — broken
        T1->>PG: SELECT balance → 100.00
        T2->>PG: SELECT balance → 100.00
        Note over T1,T2: both checks pass
        T1->>PG: INSERT withdrawal 100.00
        T2->>PG: INSERT withdrawal 100.00
        T1->>PG: COMMIT
        T2->>PG: COMMIT
        Note over PG: balance is now -100.00<br/>no bug in the code
    end

    rect rgb(230, 244, 234)
        Note over T1,PG: SERIALIZABLE — correct
        T1->>PG: SELECT balance → 100.00
        T2->>PG: SELECT balance → 100.00
        T1->>PG: INSERT + COMMIT
        T2->>PG: INSERT + COMMIT
        PG--xT2: 40001 serialization failure
        Note over T2: retried, now reads 0.00<br/>so InsufficientFunds
    end
```

---

## 6 · Corrections are appends

There is no edit path and no delete path. A correction is a new fact.

```mermaid
stateDiagram-v2
    direction LR

    [*] --> Posted: post_transaction()

    Posted --> Posted: read balance<br/>(derived)

    Posted --> Reversed: reverse_transaction()<br/>appends mirror entry

    Reversed --> Reversed: both entries remain<br/>readable forever

    note right of Posted
        immutable from the
        moment it commits.
        no UPDATE, no DELETE,
        no status column.
    end note

    note right of Reversed
        the ORIGINAL is unchanged.
        "reversed" is a property of
        the journal, not a flag on
        the row.
        UNIQUE(reverses_id) makes
        reversing twice impossible.
    end note
```

---

## 7 · Where balances come from

```mermaid
flowchart LR
    subgraph J["the journal — source of truth"]
        L1["debit  cash    100.00"]
        L2["credit wallet   97.50"]
        L3["credit fees      2.50"]
        L4["credit wallet    5.00"]
        L5["debit  wallet   10.00"]
    end

    J --> Agg["SUM by direction<br/>WHERE account_id = ?<br/>AND created_at <= as_of"]
    Agg --> Sign{"account.normal_balance"}
    Sign -->|credit| CB["credits − debits"]
    Sign -->|debit| DB2["debits − credits"]
    CB --> Out(["balance"])
    DB2 --> Out

    Out -.->|"as history grows,<br/>this scan gets slow"| Snap

    subgraph S["milestone 7 — snapshots"]
        Snap["balance_snapshots<br/>(account, seq, amount)"]
        Delta["+ SUM(lines since seq)"]
        Snap --> Delta --> Fast(["balance, O(recent)"])
    end

    classDef truth fill:#e6f4ea,stroke:#34a853,color:#111
    classDef later fill:#f1f3f4,stroke:#5f6368,stroke-dasharray: 4 4,color:#111
    class L1,L2,L3,L4,L5 truth
    class Snap,Delta,Fast later
```

---

## 8 · Scaling path

Each stage is enabled by the append-only decision. None of them are
retrofits, except partitioning — which is why it has to be decided early.

```mermaid
flowchart TD
    S1["1 · single node<br/>append-only journal"]
    S2["2 · read replicas<br/>for balance queries"]
    S3["3 · monthly RANGE partitions<br/>on the journal"]
    S4["4 · balance snapshots<br/>+ incremental sum"]
    S5["5 · sharded counters<br/>for hot accounts"]
    S6["6 · outbox table<br/>for event emission"]

    S1 --> S2 --> S3 --> S4 --> S5 --> S6

    W1["works because appends<br/>do not contend"]
    W2["works because reads are<br/>derived and tolerate staleness"]
    W3["⚠ decide early:<br/>PK must include the partition key,<br/>and you cannot FK to a<br/>partitioned table"]
    W4["turns O(history) reads<br/>into O(recent)"]
    W5["turns one contended row<br/>into N uncontended ones"]
    W6["removes commit/publish<br/>split-brain"]

    S1 -.- W1
    S2 -.- W2
    S3 -.- W3
    S4 -.- W4
    S5 -.- W5
    S6 -.- W6

    classDef stage fill:#e8f0fe,stroke:#4285f4,color:#111
    classDef why fill:#f1f3f4,stroke:#5f6368,color:#111
    classDef warn fill:#fef7e0,stroke:#fbbc04,color:#111
    class S1,S2,S3,S4,S5,S6 stage
    class W1,W2,W4,W5,W6 why
    class W3 warn
```

---

## 9 · Request lifecycle, including failures

```mermaid
flowchart TD
    In([request]) --> MW["RequestContextMiddleware<br/>request_id, timer"]
    MW --> Val{"pydantic<br/>validation"}
    Val -->|fail| E422a(["422 validation_error"])
    Val -->|pass| Sess["open session<br/>BEGIN"]

    Sess --> Dom{"domain logic"}
    Dom -->|UnbalancedTransaction| E422b(["422 unbalanced_transaction"])
    Dom -->|CurrencyMismatch| E422c(["422 currency_mismatch"])
    Dom -->|IdempotencyKeyConflict| E422d(["422 idempotency_key_conflict"])
    Dom -->|AccountNotFound| E404(["404 account_not_found"])
    Dom -->|AlreadyReversed| E409(["409 already_reversed"])
    Dom -->|"40001 after retries"| E503(["503 retry_later<br/>+ Retry-After"])
    Dom -->|unexpected| E500(["500 internal_error<br/>trace logged, not returned"])
    Dom -->|success| Ok["COMMIT"]

    Ok --> Out(["201 + X-Request-ID"])

    E422a & E422b & E422c & E422d & E404 & E409 & E503 & E500 --> RB["ROLLBACK<br/>nothing partial persists"]
    RB --> Log["structured log<br/>with request_id"]

    classDef ok fill:#e6f4ea,stroke:#34a853,color:#111
    classDef client fill:#fef7e0,stroke:#fbbc04,color:#111
    classDef server fill:#fce8e6,stroke:#d93025,color:#111
    class Ok,Out ok
    class E422a,E422b,E422c,E422d,E404,E409 client
    class E500,E503 server
```
