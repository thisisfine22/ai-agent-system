# Realestoria Valuation Pipeline

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER FLOW                                │
│                                                                 │
│  Website Form  ──►  valuation_requests  ──►  Prediction Engine  │
│       │                                          │              │
│       └──►  valuation_leads  ──►  HubSpot CRM    │              │
│                                                  ▼              │
│                                     valuation_predictions       │
│                                        (+ 3 comps)             │
│                                          │                      │
│                                          ▼                      │
│                                    Dashboard / API              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     MODEL TRAINING                              │
│                                                                 │
│  mls_sold_only_raw  ──►  mls_sold_only_clean  ──►  XGBoost     │
│   (MLSPin CSV)            (BigQuery VIEW)        train_model.py │
│                                                      │          │
│                                                      ▼          │
│                                              model_artifacts/   │
│                                              ├─ model.json      │
│                                              ├─ encoders.pkl    │
│                                              ├─ metrics.json    │
│                                              ├─ zip_lookup.json │
│                                              └─ feature_cols.json│
└─────────────────────────────────────────────────────────────────┘
```

## BigQuery Tables

| Table | Purpose | Source |
|---|---|---|
| `mls_sold_only_raw` | Raw MLSPin export (150+ columns) | CSV upload |
| `mls_sold_only_clean` | **VIEW** — cleaned, feature-engineered, filtered | SQL view on raw |
| `valuation_requests` | User form submissions (address, beds, baths, sqft) | Website form |
| `valuation_leads` | Lead info for HubSpot sync (email, name, contact) | Website form |
| `valuation_predictions` | Model outputs + comps, linked to requests | Prediction service |
| `sales` | (Existing) | — |

### Data separation logic:
- **valuation_leads** → CRM/HubSpot pipeline (lead scoring, follow-up)
- **valuation_requests** → ML input (what to predict)
- **valuation_predictions** → ML output (results + comps)
- **mls_sold_only_clean** → ML training data (what the model learns from)

## Setup Steps

### 1. Create the cleaned MLS view
Run in BigQuery:
```sql
-- File: sql/01_mls_sold_only_clean.sql
-- Creates VIEW realestoria.mls_sold_only_clean
```

### 2. Create predictions table
Run in BigQuery:
```sql
-- File: sql/02_valuation_predictions.sql
-- Creates TABLE realestoria.valuation_predictions
```

### 3. Train the model
```bash
pip install -r requirements.txt
export GOOGLE_CLOUD_PROJECT=your-project-id

# Train (reads from BigQuery, saves to model_artifacts/)
python scripts/train_model.py
```

### 4. Run predictions
```bash
# Batch: process all pending requests
python scripts/predict_service.py

# Test single prediction locally
python scripts/predict_service.py --test
```

## Model Details

### Features used (from MLSPin)
| Feature | Source Column | Type |
|---|---|---|
| sqft | SQUARE_FEET / AboveGradeFinishedArea | numeric |
| beds | NO_BEDROOMS | numeric |
| total_baths | NO_FULL_BATHS + NO_HALF_BATHS×0.5 | numeric |
| total_rooms | NO_ROOMS | numeric |
| lot_acres | ACRE / LOT_SIZE÷43560 | numeric |
| garage_spaces | GARAGE_SPACES | numeric |
| parking | TOTAL_PARKING | numeric |
| year_built | YEAR_BUILT | numeric |
| age_at_sale | sold_year - year_built | derived |
| living_levels | NO_LIVING_LEVELS | numeric |
| basement_sqft | BelowGradeFinishedArea | numeric |
| has_cooling | COOLING | boolean |
| has_basement | BASEMENT | boolean |
| finished_basement | BASEMENT_FEATURE + BelowGradeFinishedArea | boolean |
| master_bath | MASTER_BATH | boolean |
| waterfront | WATERFRONT_FLAG | boolean |
| hoa_fee | HOA_FEE | numeric |
| tax_assessment | ASSESSMENTS | numeric |
| zip_code | ZIP_CODE | categorical |
| prop_type | PROP_TYPE (SF/CC/MF) | categorical |
| style | STYLE | categorical |
| construction | CONSTRUCTION | categorical |
| sold_month | SETTLED_DATE | derived |
| recency_weight | months_since_sale | derived |

### Fallback strategy
If XGBoost model isn't available (first deploy, no training data yet),
the system falls back to `predict.py` — a heuristic model with
Redfin-sourced $/sqft data for 120+ MA ZIP codes.

### Comparable sales
Each prediction includes up to 3 recent comps from `mls_sold_only_clean`:
- Same ZIP code
- Same property type
- Similar sqft (±30%)
- Similar beds (±1)
- Sold within last 12 months
- Sorted by most recent first

## Files

```
valuation-pipeline/
├── sql/
│   ├── 01_mls_sold_only_clean.sql    # BigQuery VIEW definition
│   └── 02_valuation_predictions.sql   # Predictions table DDL
├── scripts/
│   ├── train_model.py                 # XGBoost training pipeline
│   ├── predict_service.py             # Prediction + batch processor
│   └── predict.py                     # Heuristic fallback (v2.0)
├── requirements.txt
└── README.md
```

## Retraining

Retrain monthly or when new MLS data is loaded:
```bash
# 1. Upload new MLS CSV to mls_sold_only_raw
# 2. The VIEW auto-updates (no action needed)
# 3. Retrain
python scripts/train_model.py
# 4. Deploy new model artifacts
```
