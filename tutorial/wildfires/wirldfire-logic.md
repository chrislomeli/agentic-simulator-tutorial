# Wildfire Spread Model — Technical Reference

## Overview

This document describes the simplified fire behavior model used in the wildfire spread estimator widget. It is based on the **Rothermel Fire Spread Model** (1972), the foundation of US Forest Service tools like BehavePlus and FlamMap. The implementation here is a computationally lightweight approximation suitable for simulation environments and agentic demo applications.

---

## Inputs

| Parameter | Units | Typical Range | Notes |
|---|---|---|---|
| Temperature | °F | 50 – 120 | Ambient air temperature |
| Relative Humidity (RH) | % | 2 – 60 | Lower = drier = faster spread |
| Wind Speed | mph | 0 – 60 | Mid-flame wind, strongest single amplifier |
| Slope | degrees | 0 – 45 | Uphill angle; fire accelerates upslope |
| Fuel Type | categorical | see below | Determines base spread rate and heat content |
| Fuel Moisture Content | % | 2 – 30 | % water weight relative to dry weight |

### Fuel Types

| Fuel Type | Base Spread Rate (ft/min) | Heat Content (BTU/lb) | Description |
|---|---|---|---|
| Dry grass / shrubland | 18 | 8,000 | Fast spread, lower intensity |
| Chaparral (dense shrub) | 12 | 9,500 | Moderate spread, high intensity |
| Timber litter | 6 | 8,500 | Slower spread, sustained burn |
| Logging slash (heavy) | 8 | 9,000 | Variable spread, very high intensity |

---

## The Rothermel Model — Core Concept

The Rothermel model expresses **Rate of Spread (ROS)** as a function of heat transfer through a fuel bed, modified by environmental factors. The full equation involves fuel particle geometry, packing ratio, mineral content, and moisture of extinction — these are simplified here into multiplicative factors for demo purposes.

The conceptual form is:

```
ROS = R₀ × φ_wind × φ_slope
```

Where:
- `R₀` = base spread rate for the fuel type at reference conditions
- `φ_wind` = wind factor (dimensionless multiplier)
- `φ_slope` = slope factor (dimensionless multiplier)

Environmental conditions (temperature, humidity, fuel moisture) modulate the effective `R₀` before wind and slope are applied.

---

## Implementation

### Step 1 — Environmental Modifiers

These factors scale the base spread rate based on how "ready to burn" the fuel is.

```javascript
// RH factor: lower humidity = faster spread (linear, clamped at 0)
const rhFactor = Math.max(0, 1 - rh / 60);

// Moisture factor: wetter fuel = slower spread
const moistFactor = Math.max(0, 1 - moisture / 30);

// Temperature factor: hotter = drier fuel, more receptive to ignition
const tempFactor = (temp - 50) / 70;  // normalizes 50–120°F to 0–1
```

**Why these numbers?**
- RH of 60% is roughly the upper threshold where fine fuels become non-receptive to fire spread; at 0% RH, the factor is 1.0 (fully amplified).
- Fuel moisture of 30% is near the "moisture of extinction" for fine fuels — fire won't sustain above this level.
- Temperature range 50–120°F spans typical ambient conditions in fire-prone regions.

### Step 2 — Wind and Slope Factors

```javascript
// Wind factor: each 15 mph adds ~90% more spread (empirically derived)
const windFactor = 1 + (wind / 15) * 0.9;

// Slope factor: based on tangent of slope angle (from Rothermel)
const slopeFactor = 1 + Math.tan(slope * Math.PI / 180) * 1.2;
```

**Wind** is the dominant amplifier in real fire behavior. The 0.9 coefficient per 15 mph unit approximates the Rothermel wind coefficient for mid-range fuel models. In the full model, this relationship is non-linear and fuel-dependent.

**Slope** uses the tangent of the angle because the physical mechanism is radiant preheating of uphill fuel — steeper slope = more direct exposure angle. A 30° slope roughly doubles spread rate, consistent with field observations.

### Step 3 — Rate of Spread

```javascript
let ros = fd.base
  * rhFactor
  * moistFactor
  * (0.5 + 0.5 * tempFactor)  // temperature blended at 50% weight
  * windFactor
  * slopeFactor;

ros = Math.max(0.1, ros);  // floor to prevent zero
```

Temperature is blended at 50% weight (rather than used as a pure multiplier) because its effect on spread is indirect — it influences fuel dryness over time, but at any instant the RH and fuel moisture already capture that state. This avoids double-counting.

### Step 4 — Derived Outputs

**Flame Length** — derived from fireline intensity using the Byram (1959) relationship:

```javascript
const flameLen = Math.pow(ros * fd.heatContent / 500, 0.46);
```

This approximates Byram's equation `L = 0.45 × I^0.46` where fireline intensity `I` is proportional to ROS × heat content.

**Fireline Intensity** — heat released per unit length of fire front per second:

```javascript
const intensity = ros * fd.heatContent * moistFactor * 0.9;
```

Reported in BTU/ft/s (divided by 1,000 in the display for readability). Values above ~100 BTU/ft/s are generally beyond hand-crew suppression capability; above ~1,000 BTU/ft/s, aerial resources become marginal.

**Acres per Hour** — assumes elliptical fire shape:

```javascript
const acresPerHr = (Math.PI * Math.pow(ros * 60, 2) * 2.5) / 43560;
```

- `ros * 60` converts ft/min to ft/hr (forward spread distance in 1 hour)
- The ellipse area uses `π × a × b` where `b = a / windRatio` (see spread map section)
- Factor of 2.5 accounts for the full ellipse (both forward and backing fire)
- Divided by 43,560 to convert sq ft to acres

---

## Spread Map — Elliptical Fire Model

Real fire perimeters are elliptical, not circular, because wind elongates the fire in the downwind direction. This is formalized in the **Anderson (1983)** elliptical fire growth model.

```javascript
// Semi-major axis (downwind spread distance in 1 hour)
const a = ros * 60 * scaleFactor;

// Wind ratio elongates the ellipse; higher wind = more elongated
const windRatio = 1 + wind / 40;
const b = a / windRatio;  // semi-minor axis (cross-wind width)
```

The ellipse is offset slightly forward of the ignition point (not centered on it) because backing fire (upwind spread) is much slower than heading fire. The ignition point sits approximately 15–20% of the way from the upwind edge.

A radial gradient from red (core) to amber (perimeter) represents fire intensity — highest at the core where accumulated heat is greatest, tapering at the perimeter where the fire front is actively spreading into unburned fuel.

---

## Danger Rating Logic

The overall danger rating maps ROS as a percentage of the model's maximum (40 ft/min in this implementation) to five tiers:

| Tier | ROS % of Max | Operational Meaning |
|---|---|---|
| Low | < 20% | Standard pre-attack posture |
| Moderate | 20 – 40% | Monitor; consider pre-positioning |
| High | 40 – 60% | Pre-position resources; elevated readiness |
| Very High | 60 – 80% | Active pre-positioning; restrict ignition sources |
| Extreme | > 80% | Maximum pre-positioning; potential draw-down risk |

---

## Limitations and Simplifications

These are acceptable for a demo simulation but worth noting for any production use:

1. **No spotting model** — real fires throw embers ahead of the front (spotting), which can cause fire to jump far beyond the elliptical perimeter. Spotting is fuel and wind dependent and would require a separate sub-model.

2. **Flat wind assumption** — terrain channeling in canyons and ridgelines creates local wind speeds 2–3× the ambient. The model uses a single wind value across the cell.

3. **Steady-state ROS** — Rothermel's equation gives steady-state spread under constant conditions. In reality, ROS changes continuously as conditions shift. For a grid simulation, re-evaluating ROS each time step with updated sensor data is the correct approach.

4. **No fire-atmosphere feedback** — large fires create their own wind and convection columns. This is ignored here.

5. **Uniform fuel assumption** — each cell is assumed to have a single fuel type. In reality, fuel is heterogeneous within any grid cell.

6. **Moisture of extinction** — the model uses a fixed 30% extinction threshold. Real extinction moisture varies by fuel type (fine grass ~12–15%, heavy timber ~25–30%).

---

## Recommended Extensions for Production

- Use **LANDFIRE fuel model rasters** to assign fuel type per grid cell from real geographic data
- Replace the wind factor with a **wind field** derived from terrain (e.g., WindNinja)
- Add a **spotting probability** sub-model based on flame height and wind
- Implement **time-stepped spread** — evaluate ROS each sensor polling interval and accumulate perimeter growth
- Use **fireline intensity thresholds** to drive resource typing (hand crews, engines, air tankers)

---

## References

- Rothermel, R.C. (1972). *A mathematical model for predicting fire spread in wildland fuels.* USDA Forest Service Research Paper INT-115.
- Byram, G.M. (1959). *Combustion of forest fuels.* In: Davis, K.P. Forest Fire Control and Use.
- Anderson, H.E. (1983). *Predicting wind-driven wildland fire size and shape.* USDA Forest Service Research Paper INT-305.
- Andrews, P.L. (2018). *The Rothermel Surface Fire Spread Model and Associated Developments.* USDA Forest Service RMRS-GTR-371.