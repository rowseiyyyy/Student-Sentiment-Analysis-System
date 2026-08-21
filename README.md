# Asiatech Student Sentiment Analysis System

A **web-based student feedback evaluation and sentiment analysis system** developed for **Asia Technological School of Science and Arts (Asiatech), Sta. Rosa, Laguna, Philippines**.

The system collects student evaluations and analyzes open-ended feedback using **XGBoost, DeBERTa, and RoBERTa**, combined through a **weighted soft-voting ensemble** to classify feedback as **Positive, Neutral, or Negative**.

---

## Features

### Student

* **Student login** using student number
* **Likert-scale evaluations**
* **Open-ended feedback**
* Evaluation of:

  * Faculty
  * Staff
  * Payment Services
  * School Facilities
* **Automatic sentiment analysis**

### Faculty

* **Faculty account access**
* View **sentiment analysis results**

### Administrator

* **Administrator authentication**
* **Dataset management**
* Dataset import
* **Model training and retraining**
* **Model performance comparison**
* Classification reports
* Confusion matrices
* Prediction results
* Training history

---

## Sentiment Analysis

The system uses **three machine learning models** combined through a **weighted soft-voting ensemble**.

| Model       | Role                                                |
| ----------- | --------------------------------------------------- |
| **XGBoost** | Traditional machine learning model using **TF-IDF** |
| **DeBERTa** | Transformer-based sentiment classifier              |
| **RoBERTa** | Transformer-based sentiment classifier              |

### Weighted Ensemble

![Weighted Ensemble](https://github.com/user-attachments/assets/29fa62be-36db-469f-b3c3-fbf020bce353)

The predictions from the three models are combined using a **weighted soft-voting approach** to produce the final sentiment classification.

---

## Technology Stack

### Backend

* **Python**
* **FastAPI**
* **SQLAlchemy**
* **MySQL**
* **Alembic**
* **JWT**

### Machine Learning / NLP

* **XGBoost**
* **Hugging Face Transformers**
* **PyTorch**
* **DeBERTa**
* **RoBERTa**
* **Scikit-learn**
* **TF-IDF**
* **NLTK**
* **spaCy**
* **Joblib**

### Frontend

* **HTML5**
* **CSS3**
* **JavaScript**
* **Chart.js**

---

## Project Structure

![Project Structure](https://github.com/user-attachments/assets/52678679-eea2-4945-b4b1-d8986c8e58f1)

---

## System Architecture

![SSAS System Architecture](https://github.com/user-attachments/assets/895a4fb8-eff1-4277-9ff8-1e7b603a275c)

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/rowseiyyyy/Student-Sentiment-Analysis-System.git
cd Student-Sentiment-Analysis-System
```

### 2. Create a Virtual Environment

```bash
python -m venv .venv
```

Activate the virtual environment:

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy:

```text
backend/.env.example
```

to:

```text
backend/.env
```

Configure the **database and application settings** inside `.env`.

### 5. Run Database Migrations

```bash
alembic upgrade head
```

### 6. Run the System

From the project root:

```bash
python run.py
```

---

## Testing

Run the backend tests:

```bash
cd backend
pytest
```

---

## Model Evaluation

The system supports model evaluation using:

* **Accuracy**
* **Precision**
* **Recall**
* **F1-score**
* **Confusion Matrix**
* **Classification Report**

These metrics are used to compare model performance and evaluate the effectiveness of the sentiment analysis system.

---

## Research Project

* **Project:** Student Sentiment Analysis System
* **Institution:** Asia Technological School of Science and Arts (Asiatech)
* **Location:** Sta. Rosa, Laguna, Philippines

### Researchers

* **Rosemay N. Lorena**
* **Queenie Mae C. Libres**
* **Justin Rey Q. Agapito**

---

## Project Overview

The **Asiatech Student Sentiment Analysis System (SSAS)** provides an automated platform for collecting and analyzing student feedback.

By combining **traditional machine learning** with **transformer-based NLP models**, the system aims to provide a more comprehensive analysis of student sentiment and support the evaluation of **Faculty, Staff, Payment Services, and School Facilities**.


