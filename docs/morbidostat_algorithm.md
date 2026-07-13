# Morbidostat: Exact Experiment Algorithm

Derived from Toprak et al., *Nat. Genet.* **44**, 101–105 (2012) and Toprak et al., *Nat. Protoc.* **8**, 555–567 (2013).

---

## 0. Notation and Fixed Parameters

| Symbol | Meaning | Value used |
|---|---|---|
| `V` | Culture volume (held constant) | 12 ml |
| `ΔV` | Volume added per injection | 1 ml (~8% dilution) |
| `Δt` | Growth-cycle duration | 11 min (paper) / 12 min (protocol) |
| `f` | Dilution frequency | 5 h⁻¹ |
| `r_dil` | Dilution rate | ≈ 0.4 h⁻¹ |
| `r₀` | Max growth rate, no drug | ≈ 0.8 h⁻¹ |
| `OD_THR` | Drug-injection OD threshold | 0.15 |
| `OD_MIN` | Minimum OD before any injection | 0.03 |
| `N` | Parallel cultures | 15 |
| Sampling | OD acquisition | 500 Hz DAQ → median-filtered to 1 Hz |

Two equivalent expressions for the dilution rate:

```
r_dil ≈ ΔV / (V · Δt)                 (approximation)
r_dil  = f · ln( V / (V + ΔV) )       (exact, |value| = 0.4 h⁻¹)
```

**Design invariant:** `r_dil = r₀ / 2`. Because steady state requires `r → r_dil`, the controller drives the drug concentration to whatever value inhibits growth by exactly 50% — i.e. the culture is pinned at its own, continuously moving, IC₅₀.

Drug stocks:

```
Stock A = 10 × MIC
Stock B = 50 × MIC   (= 5 × Stock A)
```

---

## 1. Per-Cycle Control Loop (the core algorithm)

Executed independently for each of the 15 vials, every `Δt`.

```
LOOP forever, per vial i:

    # ---- (1) GROW ----
    for t in [0, Δt):
        v ← DAQ voltage across photodetector_i        # 500 Hz
        OD_i(t) ← k_i · median_1s(v) + b_i            # calibration line
        record (t, OD_i(t))

    # ---- (2) ESTIMATE GROWTH RATE ----
    # robust linear regression of ln(OD) vs t over the cycle
    fit  ln OD_i(t) = ln OD_start + r_i · t           # MATLAB robustfit
    OD_start_i ← fitted value at t = 0
    OD_end_i   ← fitted value at t = Δt
    r_i        ← slope
    ΔOD_i      ← OD_end_i − OD_start_i

    # ---- (3) DECIDE ----
    if OD_end_i < OD_MIN:                 # culture too dilute to read reliably
        action ← NOTHING                  # no injection at all
    elif (OD_end_i > OD_THR) AND (ΔOD_i > 0):
        # equivalent to: r_i > r_dil  (net growth despite dilution)
        action ← INJECT_DRUG              # from active stock (A, else B)
    else:
        action ← INJECT_MEDIUM

    # ---- (4) ACTUATE ----
    if action ≠ NOTHING:
        relay_on( pump[i][action] ) for the time delivering ΔV
        relay_on( suction_pump )    to restore volume to V
        log( cycle, action, stock_used )
```

### Decision table

| `OD_end` | `ΔOD` | Action |
|---|---|---|
| < 0.03 | — | none |
| 0.03 – 0.15 | any | + ΔV medium |
| > 0.15 | ≤ 0 | + ΔV medium |
| > 0.15 | > 0 | **+ ΔV medium containing drug** |

Both branches add the *same* volume `ΔV`, so the dilution rate is invariant to the decision — only the drug content changes.

### Resulting concentration dynamics

Let `c_k` be drug concentration in the vial after cycle *k*, and `C` the concentration of the active stock:

```
INJECT_DRUG :   c_k = c_{k-1} · V/(V+ΔV) + C · ΔV/(V+ΔV)
INJECT_MEDIUM:  c_k = c_{k-1} · V/(V+ΔV)
```

This produces the characteristic sawtooth: sharp rise on drug injection, exponential washout (~8% per 11–12 min) otherwise. The controller is a bang-bang feedback loop; the *time-averaged* concentration is the controlled variable.

### Stock escalation rule

```
Start with Stock A active.
If injections from Stock A no longer bring r below r_dil within a
reasonable number of cycles (growth not inhibited):
        switch active stock → Stock B
Next day, cascade:
        A ← B
        B ← freshly prepared solution at 5 × old B
```

This keeps the ratchet running indefinitely as resistance climbs by 3+ orders of magnitude.

---

## 2. Calibration Algorithm (run before each experiment)

```
1. Dilute overnight culture to OD ≈ 0.75, add stir bar, 200 rpm.
2. for holder h in 1..15:
       place vial in h; wait 10 s; record voltage 10 s; V_h ← median
3. Remove 5 ml → spectrophotometer → true OD.
4. Add 5 ml fresh medium, mix. Repeat steps 2–3.
5. Repeat until OD < 0.03.
6. For each holder h:  robustfit  OD = k_h · V + b_h
```

Detector series resistors (~100 kΩ) are chosen so that **1 OD ≈ 2 V**. Recalibrate periodically — factors drift ~5% / month.

---

## 3. Pre-Flight Parameter Determination

```
A. r₀ measurement:      grow overnight, pumps off, log OD.
                        → r₀ and the exponential OD window (0.02–0.25).
                        Require r_dil < r₀; set r_dil ≈ r₀/2.

B. r_dil verification:  run in CHEMOSTAT mode (always inject medium).
                        Compare measured to theoretical 0.4 h⁻¹ per vial.

C. MIC:                 96-well plate, 3-fold serial drug gradient,
                        ~1000 cells/well, 24 h shaking at 30 °C.
                        MIC = lowest [drug] with no OD increase.
                        (Refine with a linear gradient if needed.)
                        → Re-measure MIC DAILY during the run.

D. Drug dose check:     grow sensitive cells to OD_THR, manually add 1 ml
                        at various concentrations. Confirm that ~10 × MIC
                        inhibits sufficiently → defines Stock A.

E. Trial run:           full algorithm on sensitive cells. Target:
                        1–2 consecutive drug injections visibly slow growth.
                        If yes → begin long-term run.
```

---

## 4. Daily Experiment Loop

```
DAY 0:
    inoculate 100 µl WT cells into 200 ml M9 + 0.4% glucose + 0.2% amicase
    incubate 30 min at 30 °C (OD still undetectable)
    dispense 12 ml into each of 15 sterile vials (stir bar inside)
    seat vials in holders, start control software

DAY d = 1 .. ~20-25:
    run the per-cycle loop continuously for 24 h
    then PAUSE and, per vial:
        (a) transfer 500 µl → fresh sterile vial with 12 ml medium
            [MANDATORY: prevents biofilm, visible within 2–3 d]
        (b) transfer 500 µl → Eppendorf + 250 µl 50% glycerol → −80 °C
            [frozen record library; also the restart point on failure]
        (c) if Stock B is in use → cascade stocks (see §1)
        (d) verify drug-stock MIC against WT
    RESUME
    compute IC₅₀ for the day (see §5)

TERMINATE when the rate of increase in resistance shows diminishing returns
(typically < 3 weeks; 20–25 d in the published run).
```

**Failure recovery:** on contamination, voltage spikes from clumping, or biofilm, restart that vial from the previous day's glycerol stock. This is the reason (b) is non-negotiable.

---

## 5. Two IC₅₀ Computations

### 5a. Dynamic IC₅₀ — from the morbidostat data itself, online

```
for each cycle k:
    fit exponential to OD(t)  → r_k, OD_start_k, OD_end_k
    dilution_k = OD_start_k / OD_end_{k-1}          # actual, not nominal
    given dilution_k and which stock fired, propagate c_k  (recursion in §1)

for each inter-injection window (between two drug injections):
    plot r vs c over the window          # a dose–response curve
    dynamic IC50 = the c at which r = 0.4 h⁻¹    # i.e. r = r_dil = r₀/2
```

Note the elegance: the *setpoint* of the controller (`r_dil = r₀/2`) is exactly the *definition* of IC₅₀, so the device reports the quantity it is regulating.

### 5b. Static IC₅₀ / MIC — offline, from the frozen library

```
20 × 96-well plates, 150 µl/well
    plate 1  = highest [drug]
    plate k  : [drug]_{k-1} = 0.6 × [drug]_k          # geometric ladder
    plate 20 = drug-free

pin frozen daily samples from master plates into experimental plates
grow 24 h, 30 °C, rapid shaking; read OD every ~30 min (plate reader)

per well:  fit exponential over 0.01 < OD < 0.1  → growth rate
normalize by the no-drug well  → r/r₀
IC50 = interpolated [drug] at r/r₀ = 0.5
MIC  = interpolated [drug] at r/r₀ = 0.1
       (or: lowest [drug] with background-subtracted OD < 0.02 at 24 h)
```

Because both use **exponential growth rates**, not endpoint OD, they are insensitive to drug-induced changes in cell size that would otherwise corrupt the OD→cell-number conversion (e.g. filamentation).

---

## 6. Experimental Design (the 2012 run)

```
Strain:   E. coli MG1655, drug-sensitive WT
Medium:   M9 + 0.4% glucose + 0.2% amicase, filter-sterilized,
          rested 2 d on bench to confirm no contamination
Temp:     30 °C
Vials:    15 = 3 drugs × 5 isogenic replicates

    CHL-1..5   chloramphenicol   (ribosome / peptidyl transferase)
    DOX-1..5   doxycycline       (ribosome / 30S)
    TMP-1..5   trimethoprim      (DHFR, folate synthesis)

Duration: ~20 d (TMP), ~25 d (CHL, DOX)
Growth-rate variability across the 15 vials: 7.5% (s.d.)
```

### Endpoint genotyping

```
1. Pick one isogenic clone from the final day of each of the 15 populations.
2. Illumina GAIIx WGS: 75-bp single-end, ~6M reads/strain.
   Align to MG1655 reference NC_000913.2; call SNPs with SAMtools.
3. Confirm high-confidence SNPs (SAMtools Q > 60) by Sanger
   (~400 bp amplicons, both directions). ~80% confirmation rate.
4. Estimate clonal abundance: re-sequence each mutated locus in
   4 additional clones from the same population.
5. Scan Illumina read coverage along the genome for
   amplifications / deletions.
```

### Time-resolved genotyping (TMP arm only)

```
for each day d, for each TMP population p:
    plate the day-d glycerol stock
    pick 4 random single colonies
    Sanger-sequence the DHFR (folA) locus + promoter
    → presence/absence of each known allele in each of the 4 clones
```

This is what resolves the *order* of mutation fixation.

### Reproducibility-of-mutational-order (RMO) test

```
RMO(seq1, seq2) = (# shared mutation pairs in the SAME order)
                − (# shared mutation pairs in REVERSE order)

Observed:  sum RMO over all 10 pairwise comparisons of the 5 TMP
           populations  →  RMO_obs = 22   (theoretical max = 28)

Null:      randomly permute mutation order within each population,
           100,000 iterations, recompute total RMO
Result:    < 200 / 100,000 permutations reach RMO ≥ 22  →  P = 0.002
Variant:   also drawing 4 of the 6 observed mutations at random per
           trajectory → only 0.073% are as ordered as observed
```

---

## 7. Key Results the Algorithm Produced

| Drug | IC₅₀ fold-increase | Trajectory | Mutational target |
|---|---|---|---|
| Trimethoprim | ~1,680× | **Stepwise** | DHFR only (small) |
| Chloramphenicol | ~870× | Smooth | efflux/transport/transcription (large) |
| Doxycycline | ~10× | Smooth | efflux/transport/transcription (large) |

- **CHL ↔ DOX:** strong reciprocal cross-resistance; different replicates reached the same plateau by *different* mutation sets (*acrA/B/R/O*, *cmr* + promoter, *marR*, *ompR*, *rpoB*, *rplD*, *fis*). No rRNA mutations despite both being ribosome inhibitors.
- **TMP:** essentially no cross-resistance; all 5 populations converged on a DHFR promoter mutation (−35C>T or −9G>A) plus coding changes near the Asp27 substrate pocket (P21L, A26T/V/S, L28R, W30C/G/R, I94L). All accumulated exactly four DHFR mutations, and in **every** replicate the *final* mutation hit codon Ala26.
- The step/smooth dichotomy is a direct readout of mutational target size: a small target means long waits for rare mutations → plateaus; a large target means short waits → smooth climb.

---

## 8. Mode Switching (same hardware, different `decide()`)

```
MORBIDOSTAT:  if OD > OD_THR and ΔOD > 0  → drug   else → medium
CHEMOSTAT:    always → medium                       (r set by nutrients)
TURBIDOSTAT:  if OD > OD_TARGET           → medium  else → nothing
                                                     (OD held constant)
```

Only the conditional in step (3) of §1 changes.
