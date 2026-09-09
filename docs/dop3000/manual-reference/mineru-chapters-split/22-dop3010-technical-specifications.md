---
title: "Chapter 22: DOP3010 technical specifications"
manual: "DOP3000 Users Manual v6.6.1"
pages: "125-130"
chapter: 22
extraction_method: mineru
split_version: "2026-07-16"
---

22 DOP3010 technical specifications

<table><tr><td colspan="2">Emission</td></tr><tr><td>Emitting frequency</td><td>variable between 0.45 MHz and 10.5 MHz, with a resolution of 1 kHz</td></tr><tr><td>Emitting power</td><td>3 levels. Approximative instantaneous maximum power for setting:low = 0.5 W, medium= 5 W, high= 35 W</td></tr><tr><td>Number of emitted cycles</td><td>2 to 32, step of 2 or 4 cycles</td></tr><tr><td>Pulse repetition frequency</td><td>selectable values between 100&#x27;000 μs and 64 μs, step of 1 μs</td></tr><tr><td>Reception</td><td></td></tr><tr><td>Number of gates</td><td>variable between 1000 and 4, step of 1 gates</td></tr><tr><td>Position of the first gate</td><td>movable by step of 1 mm but not earlier than the end of the emitted burst</td></tr><tr><td>Amplification (TGC)</td><td>amplification range from -40 to 40 dBuniformslope modeexponential amplification between two defined depth values.custom modeuser&#x27;s defined values between -40dB and +40dB in cells; variable number (from 1 to 1024), size and position of the cells.automatic computation</td></tr><tr><td>Sensitivity</td><td>&gt; -100 dBm</td></tr><tr><td>Sampling volume</td><td></td></tr><tr><td>lateral size</td><td>defined by the acoustical characteristics of the transducer.</td></tr><tr><td>longitudinal size</td><td>defined by the burst length and/or a user&#x27;s selectable internal filter. Available values:3.9, 2.9, 1.3, 1.1, 0.8, 0.7 mm(c=1500 m/s ,defined at 50% of the received signal level)</td></tr><tr><td>Display resolution:</td><td>distance between the center of each sampling volume selectable between 0.166 and 20 μs, step of 0.166 μs.</td></tr><tr><td>Velocity resolution</td><td>1 LSB, Doppler frequency given in a signed byte format.Depends on velocity scale and emitting frequency</td></tr><tr><td>Ultrasonic processor</td><td></td></tr><tr><td>Doppler frequency</td><td>computation based on a correlation algorithm</td></tr><tr><td>Wall filter</td><td>stationary echoes removed by IIR high-pass filter 2ndorder</td></tr><tr><td>Emissions per profile</td><td>between 512 and 8, any values</td></tr></table>

Signal Processing S.A. - DOP3000/3010 user's manual

22 - 1

DOP3010 technical specifications

<table><tr><td>Detection level</td><td>5 levels of the received Doppler energy may disable the computation</td></tr><tr><td>Acquisition time per profile</td><td>minimum: about 2-3 ms</td></tr><tr><td>filters on profiles</td><td>moving average: based on 2 to 1000 profiles zero values included or rejected median, based on 3 to 32 profiles</td></tr><tr><td>Velocity scale</td><td>variable positive and negative velocity range, movable origin.</td></tr><tr><td rowspan="2">Maximum velocity</td><td>Without aliasing correction, bi-directional0.5 MHz 11.72 m/s1 MHz5.86 m/s2 MHz2.93 m/s4 MHz1.46 m/s8 MHz0.73 m/s10 MHz0.59 m/s(twice if uni-directional)</td></tr><tr><td>With aliasing correction enabled, no limit (depends on flow conditions and noise level)</td></tr><tr><td>Compute and display</td><td>velocity profileDoppler energyecho profilevelocity profile with echo profile or Doppler energy velocity profile with v(t) of a selected gate power spectrum of one selected gated velocity profile and time-space velocity profile and flowrate</td></tr><tr><td>Cursor</td><td>4 available cursors in tracking mode (follow the displayed curve). Statistical values available (Mean, standard deviation, minimum, maximum)</td></tr><tr><td>External Trigger</td><td>by external signal, change in the logic state (TTL/CMOS level) automatic record capabilityTrigger delay from 0 ms to 32s, step of 1 ms</td></tr><tr><td>Velocity component</td><td>automatic computation of the projected velocity component along the flow axis</td></tr><tr><td>Replay mode</td><td>replays a recorded measure from the disk</td></tr><tr><td>Saving mode</td><td>save the past, record the future (manual trigger)</td></tr><tr><td>Additional tools</td><td>measurement of the sound velocity automatic detection of artefacts measurement of the ultrasonic field raw data acquisition (15&#x27;000 demodulated IQ values)</td></tr><tr><td>Multiplexer</td><td></td></tr><tr><td>Number of channels</td><td>10</td></tr><tr><td>Configuration parameters</td><td>all channels have their own set of parameters</td></tr></table>

22 - 2

Signal Processing S.A. - DOP3000/3010 user's manual

DOP3010 technical specifications

<table><tr><td>Switching time</td><td>0.1 ms</td></tr><tr><td>Contact resistance</td><td>0.2 ohm</td></tr><tr><td>Switching rate</td><td>recommended: 10 Hz</td></tr><tr><td>Life expectancy</td><td>\( 10^9 \) cycles</td></tr><tr><td colspan="2">Memory/Files</td></tr><tr><td>Internal memory size</td><td>2&#x27;097&#x27;152 profiles, divided in blocks from 1 to 65536 blocks</td></tr><tr><td>Configuration parameters</td><td>9 saved configurations with description</td></tr><tr><td>Data file format</td><td>binaryASCIIASCII statistical data</td></tr><tr><td colspan="2">Environment</td></tr><tr><td>Power supply</td><td>110 - 220 VAC, 50 - 60 Hz</td></tr><tr><td>Host PC Operating system</td><td>Windows® 98, XP, Vista, 7</td></tr><tr><td>Communication</td><td>via USB full speed, Connector type B</td></tr><tr><td>US interface</td><td>US probe In/Out, 10 BNC (1 for each channel)receivers probes used in UDV 2D/3D, 3 BNCEmitted burst, output, BNCEcho, (max 0.7 Vp), output impedance of 50 ohm, BNCPRF, TTL low level pulse of 100 ns at each emission, BNC</td></tr><tr><td>External trigger input</td><td>TTL level, pull up 330 ohm</td></tr><tr><td>Temperature</td><td>5 - 35 degrees</td></tr><tr><td>Sizes</td><td>235 x 98 x 347 mm</td></tr><tr><td>Weight</td><td>3 Kg</td></tr><tr><td colspan="2">Options</td></tr><tr><td colspan="2">UDV 2D/3D software package</td></tr></table>

Signal Processing S.A. - DOP3000/3010 user's manual

22 - 3

DOP3010 technical specifications

22 - 4

Signal Processing S.A. - DOP3000/3010 user's manual

Symbols

.add ....6

.bdd 6

_stat.add ....6

A

accuracy....12

acoustic impedance ....7,1

aliasing 4,1

analyzed depth ....4

arrows 4

artifacts ....4

ASCII file format ....7

attenuation ....7

B

backscattered energy ....7

batch process ....18

binary data file 7

blocks ....2

C

coded values ....14

comment 6

conversion 18

copy all the parameters .... 1

coupling medium ....2

D

default parameters ....3

default setup ....1

degree of correlation ....3

Doppler equation ....2

F

far wall ....7

FFT parameters ....5

FIFO memory ....1

file forma ....7

first channel .... 1

frequency scale ....5

G

gas layers ....1

global sampling volume ....3

H

hamming window ....5

|

identification block ....9

Imaginary velocity components ....6

input button 2

interfaces 6

internal memory ....1

J

jitter 6

K

Keep all profiles ....5

Signal Processing S.A. - DOP3000/3010 user's manual

|-1|

M

mark byte 11

maximum Doppler frequency ....1

maximum measurable depth ....1

maximum velocity ....5, 2

mean frequency ....4

measuring volume ....6

Memory full 1

N

noise 5

Nyquist limit ....4

0

origin of the measured depth ....3

origin of the velocity scale ....4

overlapping....3

P

post process....16

Pre Trigger....5

pre-recorded profiles ....3

preview button ....17

PRF ....4, 1

Q

quality of the measured values ....5

R

random echo ....3

Reading ....16

Real time ....17

real velocity vector 10

record panel ....2

record the future ....2

record the pasted ....2

reference gate ....1

reference profile ....2

reflection coefficient ....8

reflections 7

refracted angle ....9

refracted beams ....7

refraction coefficient ....9

replay mode ....18

replaying....16

re-record ....16

ringing ....7

ringing effect ....6

S

sampling volumes ....3

saturation ....9

saturation of the receiver ....7

shielded probe....5

sliding ba 18

software driver....1

software version ....18

sound speed ....9

spatial filter ....3

-2

Signal Processing S.A. - DOP3000/3010 user's manual

statistical values ....8

steady flows ....5

step by step ....18

switching time ....4

T

time between profiles ....1

time stamp ....6, 5, 12

total reflection angle ....8

Trigger condition ....4

U

unstationary flows ....5

USB rules .... 1

V

velocity is positive ....2

velocity offset ....4, 15

velocity scale factor ....5

visualize the parameters .... 16

W

wall material ....9

working directory 6

Signal Processing S.A. - DOP3000/3010 user's manual

- 3

-4

Signal Processing S.A. - DOP3000/3010 user's manual