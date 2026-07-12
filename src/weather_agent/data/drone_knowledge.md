# Drone Flying Knowledge

Curated, qualitative guidance retrieved alongside the numeric flyability
assessment. Sections are delimited by level-two headings; the retriever matches a
query (usually the hour's limiting factors) against each section's words, so
headings are named for the metrics the engine reports (wind, cold, rain,
visibility, cloud, icing, CAPE, geomagnetic).

Provenance: drone figures are DJI's official published specifications (Mini 5 Pro,
Neo, Avata 2) as of mid-2026; weather/battery reasoning draws on standard
references. They are decision-support context, not legal or airworthiness advice,
and official specs and rules can change — verify the current DJI spec page and the
UK Drone and Model Aircraft Code before flying. Where a figure is unknown it is
marked rather than guessed.

## Wind and gusts

Gusts matter more than the average wind: a steady breeze is manageable, but sharp
gusts are what flip or destabilise a light drone. The official wind-resistance
ratings are DJI Mini 5 Pro 12 m/s, DJI Avata 2 10.7 m/s, and DJI Neo 8 m/s; treat
these as outer limits, not targets, and keep margin below them. Wind is stronger
with height, so a calm surface can hide strong wind at 100-500 m; climb cautiously
and watch how hard the drone fights to hold position. Gusts are not just an
image-quality problem - they raise power draw and erode the reserve you need to
fly home. Always keep enough battery to fight a headwind on the way back; flying
out downwind is easy, returning upwind is not.

## Cold weather and batteries

All supported aircraft have a published operating range of -10 to 40 degC, but cold
sharply reduces lithium battery capacity and voltage well before the lower limit:
ionic transport slows and internal resistance rises, causing voltage sag, weaker
burst power, and earlier low-battery warnings. Below about 5 degC, expect
noticeably shorter flights. Keep spare batteries warm (inside a jacket) until use,
and hover for 30-60 seconds after take-off to warm the pack before climbing or
accelerating. Never charge a cold battery below 5 degC. Condensation can form when
a cold drone enters warm air.

## Rain and moisture

None of these drones are water-resistant. Treat any measurable precipitation, or a
high chance of it, as a no-fly. Even light drizzle or thick fog deposits moisture
on motors, electronics, and the lens. High humidity and flying through cloud can
cause condensation. If caught out, land immediately and dry the drone before the
next flight.

## Visibility, cloud and ceiling

Visibility is how far you can see horizontally, in metres. UK rules require you to
keep the drone in unaided visual line of sight, so reduced visibility (haze, mist,
fog) is a direct legal and safety limit, not just an image problem. Low-cloud
cover near 100% can mean a low cloud base that crowds the 120 m height ceiling or
forces you to fly in/just under cloud - check the actual cloud base, because the
percentage alone does not give a height. A drone without omnidirectional obstacle
sensing (Neo, Avata 2) is more exposed in poor visibility than the Mini 5 Pro,
whose forward LiDAR helps in low light.

## Freezing level and icing

The freezing level is the height at which the air reaches 0 degC; reported here
above ground level, a low or negative figure means freezing conditions within your
flight envelope. Icing is a hard no-go: ice accretion on small propellers rapidly
destroys their aerodynamic performance and the aircraft's controllability, and
none of these drones have de-icing. If the freezing level is near the surface with
any visible moisture or cloud, do not fly.

## Convective storms and CAPE

CAPE (Convective Available Potential Energy, in J/kg) measures how much energy is
available to drive rising air. Higher CAPE means a greater chance of showers,
thunderstorms, strong up/downdraughts, and turbulence - all dangerous for a light
multirotor. Roughly: below ~1000 is generally benign, ~1000-2500 is marginal
(watch the sky and radar), and above ~2500 signals real storm potential. Never fly
toward building cumulus or when thunderstorms are possible; gust fronts arrive
before the rain.

## Geomagnetic activity and GPS

The planetary K-index (Kp) runs 0 (quiet) to 9 (extreme); Kp 5 or higher is a
geomagnetic storm that can degrade GNSS/GPS accuracy and disturb the drone's
compass, raising the risk of position drift, toilet-bowling, or a flyaway. On
high-Kp days, calibrate the compass away from metal, take off with a strong
satellite lock, and be ready to switch to a non-satellite (attitude) mode and fly
manually if the drone behaves oddly.

## FPV flying with the Avata 2

The Avata 2 (377 g, EU C1, official 10.7 m/s wind resistance) is an FPV drone flown
through goggles, faster and more aggressively than a camera drone, so gusts bite
harder than the raw wind rating suggests and FPV margins should be conservative.
Crucially, it does **not** have obstacle avoidance - only downward and backward
visual positioning to aid stability - so treat it as having no collision
protection. Favour Normal mode over Manual in wind, keep speed down, avoid flying
far downwind, and use the required co-located observer; the goggles remove your
direct view of the sky and surroundings.

## Low light, dusk and night

UK rules allow Open Category night flight, but still require visual line of sight
and a green flashing light kept active throughout the flight. This application's
forecast policy recommends daylight hours only. The Mini 5 Pro's forward LiDAR
and sensing may help detect some obstacles in lower light, but cannot replace the
pilot's VLOS or full view of surrounding airspace; low light remains
operationally riskier and the horizon is harder to judge.

## DJI Neo specifics

The Neo is the lightest and most wind-sensitive supported aircraft (135 g, EU C0, official
8 m/s wind resistance, -10 to 40 degC). It has **no obstacle avoidance** - only
downward visual positioning - so never rely on it to dodge obstacles; keep it
close, low, in light wind, and in open areas. With ~18 minutes of flight time and
very low mass it has little margin to fight wind home, and its app-control range
is only ~50 m (much further on a dedicated controller).

## DJI Mini 5 Pro specifics

The Mini 5 Pro is the best all-rounder: official 12 m/s wind resistance,
omnidirectional binocular vision with forward LiDAR (the only one here with real
obstacle sensing and useful low-light/night detection), and the longest flight
time. Forward LiDAR has limits - it cannot detect low-reflectivity or glass
surfaces and fails in very bright light - so it is an aid, not a guarantee. With
the standard-battery configuration is an EU C0 aircraft below 250 g. DJI also
documents a distinct Plus-battery/C1 bundle; fitting the Plus battery to a C0
aircraft exceeds its C0 MTOM. Select the exact configuration rather than
inferring a class mark from measured weight.

## DJI Avata 2 specifics

The Avata 2 (377 g, EU C1, official 10.7 m/s wind resistance, -10 to 40 degC) is an
FPV platform requiring goggles and a motion or FPV controller. It supports Smart,
Low-Battery, and Failsafe Return-to-Home, but has **no obstacle avoidance** (only
downward and backward visual positioning). Real FPV missions use more energy than
the lab flight time suggests because of high speed and throttle transients, so
keep a larger reserve, especially in cold air.

## Pre-flight checklist

Check the forecast for gusts, precipitation, temperature, and visibility across
the whole intended flight window, not just the start. Confirm airspace and any
Flight Restriction Zones (CAA Drone Assist / Altitude Angel). Update firmware,
calibrate the compass if prompted, start with full warm batteries, and confirm a
strong satellite lock before take-off. Set a sensible return-to-home altitude
above local obstacles.
