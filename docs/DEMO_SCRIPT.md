# AAGAM — 5-Minute Live Demonstration Rehearsal Script

**Project:** Adaptive AI-Grid Assimilation Model (AAGAM)  
**Hackathon / Problem Statement:** Smart India Hackathon 2026 — PS 26081 (MoES / NCMRWF)  
**Document Type:** Speaker Script & Live Presentation Walkthrough (PRD §17)  
**Target Duration:** Exactly 5 Minutes + 2 Minutes Q&A  

---

## Storyline Overview & Time Allocation

| Step | Topic | Screen / Tab | Duration |
|---|---|---|---|
| **1** | National Overview & Problem Statement | Interactive Synoptic Map | 0:00 – 0:45 |
| **2** | Station Deep Dive (Delhi / Mumbai) | Forecast Detail View | 0:45 – 1:30 |
| **3** | Extreme Alert Engine & Spread | Active Alerts Drawer | 1:30 – 2:10 |
| **4** | Verification & Skill Score Curves | Skill Scores Tab | 2:10 – 2:50 |
| **5** | Dynamic Regional Weights | Model Weights View | 2:50 – 3:30 |
| **6** | AI Assistant Live Reasoning | AI Assistant Drawer | 3:30 – 4:25 |
| **7** | Admin Rollback & High Availability | Admin / Architecture | 4:25 – 5:00 |

---

## Step-by-Step Speaker Script

### Step 1: National Overview & Problem Statement (0:00 – 0:45)
- **UI Action:** Open Dashboard (`/`). Show full-screen map of India displaying 40 synoptic stations with color-coded alert rings.
- **Speaker:**
  > *"Good morning, esteemed judges. Welcome to AAGAM — the Adaptive AI-Grid Assimilation Model, built for MoES and NCMRWF under Problem Statement 26081.*  
  > *India's weather forecasting faces a fundamental dilemma: Global Numerical Weather Prediction models like NOAA GFS, ECMWF IFS, and DWD ICON, alongside cutting-edge AI models like ECMWF AIFS, frequently disagree by 5 to 15 degrees Celsius or 40 to 80 millimeters of rainfall. Choosing any single model leads to missed extreme events or false alarms.*  
  > *AAGAM solves this by implementing an adaptive, AI-driven hierarchical stacking framework. Rather than a naive average, AAGAM dynamically weights each model based on regional topography, climate season, and forecast lead time."*

---

### Step 2: Station Deep Dive (0:45 – 1:30)
- **UI Action:** Click on **Delhi (Safdarjung)** marker on the map. The side panel expands showing the 7-day forecast comparison.
- **Speaker:**
  > *"Here in New Delhi, look at Day 1 through Day 3. Notice the divergence: ECMWF IFS predicts 36.2°C, GFS predicts 39.1°C, and ICON predicts 37.0°C.*  
  > *AAGAM synthesizes these inputs through our regularized Ridge and LightGBM blending pipeline to produce the optimal consensus: 37.4°C, accompanied by an ensemble spread of ±1.2°C.*  
  > *Notice that for every single forecast, AAGAM outputs not just a point value, but the underlying individual model inputs, the consensus spread, and a degraded-mode indicator ensuring total transparency."*

---

### Step 3: Extreme Alert Engine & Uncertainty Spread (1:30 – 2:10)
- **UI Action:** Click the **Alerts** filter in the top navigation or click on an amber/red marker (e.g. Mumbai or Cherrapunji).
- **Speaker:**
  > *"Our alert system is built directly on IMD operational criteria. When predicted rainfall exceeds 64.5 mm (Heavy Rain) or temperature exceeds 40°C with significant anomaly, AAGAM triggers an alert.*  
  > *Crucially, AAGAM's alert engine calculates 'models_over_threshold' and ensemble spread. If 3 out of 4 models exceed the severe threshold with tight spread, confidence is HIGH. If only 1 model spikes while spread is large, forecasters are immediately warned of high uncertainty. This directly reduces false-positive disaster mobilizations."*

---

### Step 4: Verification & Skill Score Demonstration (2:10 – 2:50)
- **UI Action:** Switch to the **Skill & Verification** tab (`/skill`). Display the 1–7 day Lead-Time MAE degradation curves.
- **Speaker:**
  > *"The true test of any operational model is empirical verification. Here we see the historical MAE and RMSE curves evaluated across our 40 stations over the past 90 days.*  
  > *Notice the yellow curve: that is AAGAM. Across lead days 1 through 7, AAGAM consistently achieves a 12% to 22% reduction in Mean Absolute Error compared to raw GFS and raw ECMWF. Even as raw models degrade sharply past Day 4, our adaptive bias correction dampens systematic drift."*

---

### Step 5: Dynamic Regional Weights (2:50 – 3:30)
- **UI Action:** Click the **Weights Inspector** view (`/weights`).
- **Speaker:**
  > *"How does AAGAM achieve this? Let's inspect the weights. Notice that the weights are not static.*  
  > *In the Northwest Plains during pre-monsoon heatwaves, ECMWF and AIFS receive higher weights for temperature due to superior boundary layer physics. Conversely, in the Western Ghats during the monsoon, high-resolution ICON receives boosted precipitation weight.*  
  > *Furthermore, our fallback hierarchy ensures that if a model feed is delayed, the system gracefully degrades from regional-seasonal weights to global weights, and ultimately to uniform mean with a flag — never crashing."*

---

### Step 6: AI Assistant Live Reasoning Drill (3:30 – 4:25)
- **UI Action:** Open the **Assistant Drawer** (`Cmd/Ctrl + K` or floating button). Click quick prompt: *"Compare models for Delhi tomorrow"* or type: *"What is the rainfall forecast for Mumbai over the next 3 days?"*
- **Speaker:**
  > *"Operational forecasters need instant answers during emergency briefings. We integrated a real-time AI Assistant powered by Groq and Llama 3.3.*  
  > *Watch the execution trace: The assistant does not hallucinate. It autonomously calls our deterministic backend tools: `get_forecast` and `compare_models`. It streams back a verified markdown data table and provides direct citations.*  
  > *Behind the scenes, our custom Number Guard interceptor validates every single figure against raw backend JSON before display, guaranteeing 100% numerical fidelity."*

---

### Step 7: Admin Rollback & High Availability (4:25 – 5:00)
- **UI Action:** Briefly show the **Architecture / Model Registry** or terminal drill output.
- **Speaker:**
  > *"Finally, AAGAM is built for mission-critical enterprise deployment. In production, we maintain automated nightly Parquet backups with disaster recovery restoration verified in under 600 milliseconds.*  
  > *Our model registry enforces zero-downtime rollbacks via atomic database transactions, switching active model versions in 330 milliseconds with instant cache invalidation.*  
  > *AAGAM bridges raw numerical supercomputing with AI-driven operational certainty. Thank you, and we welcome your questions."*

---

## Anticipated Judge Questions & Recommended Responses

1. **Q: How is this different from a simple ensemble mean?**  
   *A:* An ensemble mean gives equal 25% weight to every model regardless of past performance. If one model has a known 3°C cold bias in the Thar Desert or consistently over-predicts orographic rain, equal averaging dilutes the good models. AAGAM learns regional, seasonal, and lead-dependent error distributions via regularized Ridge regression and LightGBM, outperforming simple mean by 12–22% in verified MAE.

2. **Q: What happens if Open-Meteo or an upstream model goes down?**  
   *A:* Our pipeline has 4-tier graceful degradation. If 1 or 2 models fail to arrive, AAGAM automatically routes to our dynamic fallback weights (`drop_regime` $\to$ `global` $\to$ `equal_mean`), raises the `degraded=true` flag, and displays an advisory banner on the dashboard without interrupting forecaster workflows.

3. **Q: Are you claiming to replace physical NWP?**  
   *A:* Not at all. AAGAM is an AI-grid assimilation and post-processing model. We rely on the physical primitive equation integrations of GFS, IFS, and ICON. We act as an intelligent assimilation layer that corrects systematic biases and optimizes multi-model consensus for regional Indian conditions.
