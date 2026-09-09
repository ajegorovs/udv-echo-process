---
title: "Chapter 21: DOP3000 technical specifications"
manual: "DOP3000 Users Manual v6.6.1"
pages: "120-124"
chapter: 21
extraction_method: mineru
split_version: "2026-07-16"
---

21 DOP3000 technical specifications

<table><tr><td colspan="2">Emission</td></tr><tr><td>Emitting frequency</td><td>without package “Variable frequency”Fixed, defined at purchase between 0.5, 1, 2, 4, 8 and 10 MHzwith “Variable frequency” package installedvariable between 0.45 MHz and 10.5 MHz, with a resolution of 1 kHz</td></tr><tr><td>Emitting power</td><td>3 levels. Approximative instantaneous maximum power for setting:low = 0.5 W, medium= 5 W, high= 35 W</td></tr><tr><td>Number of emitted cycles</td><td>without package “Extended resolution”Fixed, 4 cycleswith “Extended resolution” installed2 to 32, step of 2 or 4 cycles</td></tr><tr><td>Pulse repetition frequency</td><td>without package “Extended resolution”selectable values between 10’000 μs and 64 μs, step of 1 μswith “Extended resolution” installedselectable values between 100’000 μs and 64 μs, step of 1 μs</td></tr><tr><td colspan="2">Reception</td></tr><tr><td>Number of gates</td><td>without package “Extended number of gates”variable between 100 and 4, not user’s selectablewith “Extended number of gates” installedvariable between 1000 and 4, step of 1 gates</td></tr><tr><td>Position of the first gate</td><td>without package “Extended number of gates”fixed. Echo sampled after the end of the emitted burstwith “Extended number of gates” installedmovable by step of 1 mm but not earlier than the end of the emitted burst</td></tr><tr><td>Amplification (TGC)</td><td>amplification range from -40 to 40 dB</td></tr><tr><td></td><td>without package “variable TGC”uniform or automatic computationwith “variable TGC” installed*uniformslope modeexponential amplification between two defined depth values.custom modeuser’s defined values between -40dB and +40dB in cells;variable number (from 1 to 1024), size and position of the cells.automatic computation</td></tr></table>

Signal Processing S.A. - DOP3000/3010 user's manual

21 - 1

DOP3000 technical specifications

<table><tr><td>Sensitivity</td><td>&gt; -100 dBm</td></tr><tr><td>Sampling volume</td><td></td></tr><tr><td>lateral size</td><td>defined by the acoustical characteristics of the transducer.</td></tr><tr><td rowspan="2">longitudinal size</td><td>without package “Extended resolution” defined by the burst length but not smaller than 1.1 mm. Not user’s selectable</td></tr><tr><td>with “Extended resolution” installed defined by the burst length or a user’s selectable internal filter. Available values:3.9, 2.9, 1.3, 1.1, 0.8, 0.7 mm(c=1500 m/s ,defined at 50% of the received signal)</td></tr><tr><td>Display resolution:</td><td>without package “Extended resolution”2 values as mentioned in the table below</td></tr></table>

Table 7:

<table><tr><td colspan="7">time between gates in μs</td></tr><tr><td>US freq MHz</td><td>0.5</td><td>1</td><td>2</td><td>4</td><td>8</td><td>10</td></tr><tr><td>Corse</td><td>20</td><td>10</td><td>10</td><td>5</td><td>3</td><td>2</td></tr><tr><td>Fine</td><td>5</td><td>3</td><td>2</td><td>1</td><td>1</td><td>0.5</td></tr></table>

with “Extended resolution” installed distance between the center of each sampling volume selectable between 0.166 and 20 μs, step of 0.166 μs.

<table><tr><td>Velocity resolution</td><td>1 LSB, Doppler frequency given in a signed byte format.Depends on velocity scale and emitting frequency</td></tr><tr><td>Ultrasonic processor</td><td></td></tr><tr><td>Doppler frequency</td><td>computation based on a correlation algorithm</td></tr><tr><td>Wall filter</td><td>stationary echoes removed by IIR high-pass filter \( 2^{nd} \) order</td></tr><tr><td>Emissions per profile</td><td>without package “additional compute mode”automatically adjusted as a function of desired quality factorwith package “additional compute mode” installedbetween 1024 and 8, any values</td></tr><tr><td>Detection level</td><td>5 levels of the received Doppler energy may disable the computation</td></tr><tr><td>Acquisition time per profile</td><td>minimum: about 2-3 ms</td></tr><tr><td>filters on profiles</td><td>without package “additional compute mode”nonewith package “additional compute mode” installedmoving average:based on 2 to 32000 profileszero values included or rejected</td></tr></table>

21 - 2

Signal Processing S.A. - DOP3000/3010 user's manual

DOP3000 technical specifications

<table><tr><td></td><td>median, based on 3 to 32 profiles</td></tr><tr><td rowspan="2">Velocity scale</td><td>without package “additional compute mode”bi -directionnal velocity scale (equal range)</td></tr><tr><td>with package “additional compute mode” installedvariable positive and negative velocity range</td></tr><tr><td rowspan="2">Maximum velocity</td><td>Without aliasing correction, bi-directional0.5 MHz 11.72 m/s1 MHz5.86 m/s2 MHz2.93 m/s4 MHz1.46 m/s8 MHz0.73 m/s10 MHz0.59 m/s(twice if uni-directional)</td></tr><tr><td>With aliasing correction enabled, no limit (depends on flow conditions and noise level)Aliasing correction available with “additional compute mode”software package.</td></tr><tr><td rowspan="2">Compute and display</td><td>without package “additional compute mode”velocity profileecho profile</td></tr><tr><td>with package “additional compute mode”velocity profileecho profilevelocity profile with echo profilevelocity profileDoppler energyecho profilevelocity profile with echo profile or Doppler energyvelocity profile with v(t) of one selected gatepower spectrum of one selected gatedvelocity and time spacevelocity profile with flowrate</td></tr><tr><td rowspan="2">Cursor</td><td>without package “additional compute mode”None</td></tr><tr><td>with package “additional compute mode” installed4 available cursors in tracking mode (follow the displayed curve). Statistical values available (Mean, standard deviation, minimum, maximum)</td></tr><tr><td rowspan="2">External Trigger</td><td>without package “advanced Trigger”None</td></tr><tr><td>wth package “advanced Trigger” installedby external signal, change in the logic state (TTL/CMOS level)automatic record capabilityTrigger delay from 0 ms to 32s, step of 1 ms</td></tr><tr><td>Velocity component</td><td>automatic computation of the projected velocity component</td></tr></table>

Signal Processing S.A. - DOP3000/3010 user's manual

21 - 3

DOP3000 technical specifications

<table><tr><td></td><td>along the flow axis</td></tr><tr><td>Replay mode</td><td>replays a recorded measure from the disk</td></tr><tr><td>Saving mode</td><td>save the past, record the future (manual trigger)</td></tr><tr><td colspan="2">Memory/Files</td></tr><tr><td rowspan="2">Internal memory size</td><td>without package “advanced Record”1000 profiles</td></tr><tr><td>with package “advanced Record” installed64&#x27;000 profiles, 65&#x27;536 blocks</td></tr><tr><td rowspan="2">Configuration parameters</td><td>without package “advanced Record”1 saved configuration</td></tr><tr><td>with package “advanced Record” installed9 saved configurations with description</td></tr><tr><td>Data file format</td><td>binaryASCIIASCII statistical data</td></tr><tr><td colspan="2">Environment</td></tr><tr><td>Power supply</td><td>110 - 220 VAC, 50 - 60 Hz</td></tr><tr><td>Host PC Operating system</td><td>Windows® XP</td></tr><tr><td>Communication</td><td>via USB full speed, Connector type B</td></tr><tr><td>US interface</td><td>US probe In/Out, BNCEcho, (max 0.7 Vp), output impedance of 50 ohmPRF, TTL low level pulse of 100 ns at each emission</td></tr><tr><td>External trigger input</td><td>TTL level, pull up 330 ohm</td></tr><tr><td>Temperature</td><td>5 - 35 degrees</td></tr><tr><td>Sizes</td><td>235 x 98 x 347 cm</td></tr><tr><td>Weight</td><td>3 Kg</td></tr><tr><td colspan="2">Options</td></tr><tr><td>software packages</td><td>variable frequencyvariable gatesadditional compute modevariable resolutionadvanced recording featuresvariable TGCultrasonic field measurementsound velocity measurementadvanced Trigger</td></tr></table>

21 - 4

Signal Processing S.A. - DOP3000/3010 user's manual

DOP3010 technical specifications

