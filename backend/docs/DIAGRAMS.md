# System Diagrams

These diagrams use [Mermaid](https://mermaid.js.org/) syntax. They render
automatically on GitHub/GitLab, in most modern Markdown viewers, and in
the [Mermaid Live Editor](https://mermaid.live).

---

## 1. ER Diagram

```mermaid
erDiagram
    USERS ||--o{ EVALUATIONS : submits
    EVALUATIONS ||--|| PREDICTIONS : has
    TRAINING_HISTORY {
        string id PK
        string algorithm
        string status
        string dataset_filename
        int dataset_size
        float accuracy
        float precision
        float recall
        float f1_score
        float macro_f1
        float weighted_f1
        float training_time_seconds
        float inference_time_ms
        float memory_usage_mb
        json confusion_matrix
        json classification_report
        json hyperparameters
        bool is_production_model
        datetime created_at
    }

    USERS {
        string id PK
        string full_name
        string email
        string hashed_password
        string role
        bool is_active
        datetime created_at
        datetime updated_at
    }

    EVALUATIONS {
        string id PK
        string user_id FK
        string category
        text comment
        text cleaned_comment
        datetime created_at
    }

    PREDICTIONS {
        string id PK
        string evaluation_id FK
        string svm_prediction
        float svm_confidence
        string naive_bayes_prediction
        float naive_bayes_confidence
        string logistic_regression_prediction
        float logistic_regression_confidence
        string official_prediction
        string algorithm_used
        float confidence_score
        float processing_time_ms
        datetime created_at
    }
```

> `training_history` is intentionally not linked by foreign key to
> `evaluations` / `predictions` — it tracks model training runs
> independently of individual student submissions.

---

## 2. Architecture Diagram

```mermaid
flowchart TB
    subgraph Client
        A[Student / Admin Web or Mobile App]
    end

    subgraph API["FastAPI Backend"]
        B[main.py<br/>CORS · Rate Limiting · Exception Handlers]
        C[Auth Router<br/>/auth]
        D[Evaluation Router<br/>/evaluation]
        E[Prediction Router<br/>/predict]
        F[Analytics Router<br/>/analytics]
        G[ML Router<br/>/ml]
    end

    subgraph Services["Service Layer"]
        H[Preprocessing Service<br/>clean_for_classical / clean_for_transformer]
        I[SVM Service<br/>TF-IDF · research only]
        J[Naive Bayes Service<br/>TF-IDF · research only]
        K[Logistic Regression Service<br/>TF-IDF · research only]
        R[Multilingual MiniLM Service<br/>ONNX Runtime · LIVE]
        L[Training / Import Orchestration Service]
        M[Prediction Pipeline Service]
        N[Analytics Service]
    end

    subgraph Data["Persistence"]
        O[(MySQL<br/>Users / Evaluations / Predictions / TrainingHistory)]
        P[/ML Artifacts<br/>svm_model.pkl · naive_bayes_model.pkl · logreg_model.pkl<br/>tfidf_vectorizer_*.pkl · minilm_sentiment/onnx/]
    end

    Q[HuggingFace Hub<br/>rowseiy/minilm-sentiment]

    A -->|HTTPS + JWT| B
    B --> C & D & E & F & G

    D --> M
    E --> M
    M --> H
    M --> R
    G --> L
    L --> H
    L --> I
    L --> J
    L --> K
    L --> R
    F --> N

    I <--> P
    J <--> P
    K <--> P
    R <--> P
    R <--> Q

    C --> O
    D --> O
    F --> O
    L --> O
    M --> O
```

---

## 3. Sequence Diagram — Student Submits an Evaluation

```mermaid
sequenceDiagram
    actor Student
    participant API as FastAPI (/evaluation)
    participant Pipeline as Prediction Pipeline Service
    participant MiniLM as Multilingual MiniLM Service (ONNX)
    participant DB as MySQL

    Student->>API: POST /evaluation {category, comment}
    API->>DB: INSERT Evaluation
    API->>Pipeline: run_prediction_pipeline(db, comment)

    Pipeline->>DB: get_production_algorithm(db) → Multilingual MiniLM
    Pipeline->>Pipeline: clean_for_transformer(text)
    Pipeline->>MiniLM: predict(text)
    MiniLM-->>Pipeline: (label, confidence, probabilities)

    Note over Pipeline,MiniLM: MiniLM is the ONLY live model — there is no
    inference fallback. If it cannot serve, the request fails with HTTP 503.

    Pipeline-->>API: {official_prediction, algorithm_used, confidence_score}
    API->>DB: INSERT Prediction (research columns NULL + official result)
    API-->>Student: 201 Created (Evaluation + Prediction)
```

---

## 4. Sequence Diagram — Admin Imports Training Results & Compares Models

```mermaid
sequenceDiagram
    actor Admin
    participant Colab as Colab Training Notebook
    participant API as FastAPI (/ml)
    participant Training as Import/Training Service
    participant DB as MySQL
    participant FS as Filesystem (app/ml/*)

    Admin->>API: POST /ml/dataset/upload (CSV)
    API->>FS: save + validate CSV
    API-->>Admin: 201 {rows, categories, distribution}

    Admin->>Colab: run SVM / Naive Bayes / Logistic Regression + MiniLM
    Colab-->>Admin: metrics.json (dashboard_export)
    Colab->>API: POST /ml/import-results (metrics_json)
    API->>Training: normalize_metrics_payload(payload)
    Training->>DB: INSERT TrainingHistory per approved approach
    Training->>DB: mark Multilingual MiniLM is_production_model = true
    Training->>FS: write comparison_results.json / model_metadata.json
    Training-->>API: {imported_algorithms, production_model, recommended_model}
    API-->>Admin: 200 Import complete
```

> There is no `POST /ml/train` endpoint — heavy training runs outside the
> API (Colab or `scripts/train_models.py`) and only the resulting metrics
> are imported. Research approaches are **display-only**; MiniLM always
> remains the live production model.
