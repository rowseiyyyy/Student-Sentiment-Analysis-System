# System Diagrams

These diagrams use [Mermaid](https://mermaid.js.org/) syntax. They render
automatically on GitHub/GitLab, in most modern Markdown viewers, and in
the [Mermaid Live Editor](https://mermaid.live).

---

## (ER) Diagram

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
        string random_forest_prediction
        float random_forest_confidence
        string bert_prediction
        float bert_confidence
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
        H[Preprocessing Service]
        I[SVM Service]
        J[Random Forest Service]
        K[BERT Service]
        L[Training Orchestration Service]
        M[Prediction Pipeline Service]
        N[Analytics Service]
    end

    subgraph Data["Persistence"]
        O[(MySQL<br/>Users / Evaluations / Predictions / TrainingHistory)]
        P[/ML Artifacts<br/>svm_model.pkl · random_forest.pkl · tfidf_vectorizer.pkl/]
    end

    Q[HuggingFace Hub<br/>cardiffnlp/twitter-roberta-base-sentiment]

    A -->|HTTPS + JWT| B
    B --> C & D & E & F & G

    D --> M
    E --> M
    M --> H
    M --> I
    M --> J
    M --> K
    G --> L
    L --> H
    L --> I
    L --> J
    L --> K
    F --> N

    I <--> P
    J <--> P
    K <--> Q

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
    participant SVM as SVM Service
    participant RF as Random Forest Service
    participant BERT as BERT Service
    participant DB as MySQL

    Student->>API: POST /evaluation {category, comment}
    API->>DB: INSERT Evaluation
    API->>Pipeline: run_prediction_pipeline(text)

    Pipeline->>SVM: predict(text)
    SVM-->>Pipeline: (label, confidence)

    Pipeline->>RF: predict(text)
    RF-->>Pipeline: (label, confidence)

    Pipeline->>BERT: predict(text)
    BERT-->>Pipeline: (label, confidence)

    Pipeline->>DB: read production model flag (TrainingHistory)
    Pipeline-->>API: {svm, rf, bert, official_prediction, algorithm_used}

    API->>DB: INSERT Prediction (all model outputs + official)
    API-->>Student: 201 Created (Evaluation + Prediction)
```

---

## 4. Sequence Diagram — Admin Trains & Compares Models

```mermaid
sequenceDiagram
    actor Admin
    participant API as FastAPI (/ml)
    participant Training as Training Orchestration Service
    participant SVM as SVM Service
    participant RF as Random Forest Service
    participant BERT as BERT Service
    participant DB as MySQL
    participant FS as Filesystem (app/ml/*)

    Admin->>API: POST /ml/dataset/upload (CSV)
    API->>FS: save + validate CSV
    API-->>Admin: 201 {rows, categories, distribution}

    Admin->>API: POST /ml/train {dataset_filename}
    API->>Training: run_full_training(csv_path)

    Training->>Training: load_and_validate_dataset()
    Training->>Training: fit shared TF-IDF vectorizer

    Training->>SVM: train(texts, labels, vectorizer)
    SVM->>FS: save svm_model.pkl
    SVM-->>Training: metrics (accuracy, F1, confusion matrix...)
    Training->>DB: INSERT TrainingHistory (SVM)

    Training->>RF: train(texts, labels, vectorizer)
    RF->>FS: save random_forest.pkl
    RF-->>Training: metrics
    Training->>DB: INSERT TrainingHistory (Random Forest)

    Training->>BERT: evaluate on identical held-out split
    BERT-->>Training: metrics
    Training->>DB: INSERT TrainingHistory (BERT)

    Training->>Training: select best model (max weighted F1)
    Training->>DB: UPDATE TrainingHistory SET is_production_model
    Training->>FS: write comparison_results.json / model_metadata.json

    Training-->>API: {best_model, results}
    API-->>Admin: 200 {message, best_model, metrics}
```
