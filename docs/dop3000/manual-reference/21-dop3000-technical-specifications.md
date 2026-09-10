# 21. DOP3000 technical specifications

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 119-122.

---

<!-- source-pdf-page: 119 -->
## Source PDF page 119

#### Layout-preserving transcription

```text
21 DOP3000 technical specifications
Emission

Emitting frequency                  without package "Variable frequency"
                                    Fixed, defined at purchase between 0.5, 1, 2, 4, 8 and 10 MHz

                                    with "Variable frequency" package installed
                                    variable between 0.45 MHz and 10.5 MHz, with a resolution of 1
                                    kHz

Emitting power                      3 levels. Approximative instantaneous maximum power for
                                    setting:
                                    low = 0.5 W, medium= 5 W, high= 35 W

Number of emitted cycles            without package "Extended resolution"
                                    Fixed, 4 cycles

                                    with "Extended resolution" installed
                                    2 to 32, step of 2 or 4 cycles

Pulse repetition frequency          without package "Extended resolution"
                                    selectable values between 10'000 μs and 64 μs, step of 1 μs

                                    with "Extended resolution" installed
                                    selectable values between 100'000 μs and 64 μs, step of 1 μs
Reception

Number of gates                     without package "Extended number of gates"
                                    variable between 100 and 4, not user's selectable

                                    with "Extended number of gates" installed
                                    variable between 1000 and 4, step of 1 gates

Position of the first gate          without package "Extended number of gates"
                                    fixed. Echo sampled after the end of the emitted burst

                                    with "Extended number of gates" installed
                                    movable by step of 1 mm but not earlier than the end of the
                                    emitted burst

Amplification (TGC)                 amplification range from -40 to 40 dB


                                    without package "variable TGC"
                                    uniform or automatic computation

                                    with "variable TGC" installed*
                                    uniform
                                    slope mode
                                    exponential amplification between two defined depth values.
                                    custom mode
                                    user's defined values between -40dB and +40dB in cells;
                                    variable number (from 1 to 1024), size and position of the cells.
                                    automatic computation
```

---

<!-- source-pdf-page: 120 -->
## Source PDF page 120

#### Layout-preserving transcription

```text
  Sensitivity                           > -100 dBm
  Sampling volume

  lateral size                          defined by the acoustical characteristics of the transducer.

  longitudinal size                     without package "Extended resolution"
                                        defined by the burst length but not smaller than
                                        1.1 mm. Not user's selectable

                                        with "Extended resolution" installed
                                        defined by the burst length or a user's selectable internal filter.
                                        Available values:
                                        3.9, 2.9, 1.3, 1.1, 0.8, 0.7 mm
                                        (c=1500 m/s ,defined at 50% of the received signal)

  Display resolution:                   without package "Extended resolution"
                                        2 values as mentionned in the table below

                                                      Table 7:
                                 time between gates in μs

                                 US      freq   0.5    1    2    4   8   10
                                 MHz

                                 Corse          20     10   10   5   3   2

                                 Fine           5      3    2    1   1   0.5



                                        with "Extended resolution" installed
                                        distance between the center of each sampling volume
                                        selectable between 0.166 and 20 μs, step of 0.166 μs.

  Velocity resolution                   1 LSB, Doppler frequency given in a signed byte format.
                                        Depends on velocity scale and emitting frequency
  Ultrasonic processor

  Doppler frequency                     computation based on a correlation algorithm

  Wall filter                           stationary echoes removed by IIR high-pass filter 2nd order

  Emissions per profile                 without package "additional compute mode"
                                        automatically adjusted as a function of desired quality factor

                                        with package "additional compute mode" installed
                                        between 1024 and 8, any values

  Detection level                       5 levels of the received Doppler energy may disable the
                                        computation

  Acquisition time per profile          minimum: about 2-3 ms

  filters on profiles                   without package "additional compute mode"
                                        none

                                        with package "additional compute mode" installed
                                        moving average:
                                          based on 2 to 32000 profiles
                                          zero values included or rejected
```

---

<!-- source-pdf-page: 121 -->
## Source PDF page 121

#### Layout-preserving transcription

```text
                                  median, based on 3 to 32 profiles

Velocity scale                    without package "additional compute mode"
                                  bi -directionnal velocity scale (equal range)

                                  with package "additional compute mode" installed
                                  variable positive and negative velocity range

Maximum velocity                  Without aliasing correction, bi-directional
                                  0.5 MHz 11.72 m/s
                                  1 MHz5.86 m/s
                                  2 MHz2.93 m/s
                                  4 MHz1.46 m/s
                                  8 MHz0.73 m/s
                                  10 MHz0.59 m/s
                                   (twice if uni-directional)

                                  With aliasing correction enabled, no limit (depends on flow
                                  conditions and noise level)
                                  Aliasing correction available with "additional compute mode"
                                  software package.

Compute and display               without package "additional compute mode"
                                  velocity profile
                                  echo profile

                                  with package "additional compute mode"
                                  velocity profile
                                  echo profile
                                  velocity profile with echo profile
                                  velocity profile
                                  Doppler energy
                                  echo profile
                                  velocity profile with echo profile or Doppler energy
                                  velocity profile with v(t) of one selected gate
                                  power spectrum of one selected gated
                                  velocity and time space
                                  velocity profile with flowrate


Cursor                            without package "additional compute mode"
                                  None

                                  with package "additional compute mode" installed
                                  4 available cursors in tracking mode (follow the displayed
                                  curve). Statistical values available (Mean, standard deviation,
                                  minimum, maximum)

External Trigger                  without package "advanced Trigger"
                                  None

                                  wth package "advanced Trigger" installed
                                  by external signal, change in the logic state (TTL/CMOS level)
                                  automatic record capability
                                  Trigger delay from 0 ms to 32s, step of 1 ms

Velocity component                automatic computation of the projected velocity component
```

---

<!-- source-pdf-page: 122 -->
## Source PDF page 122

#### Layout-preserving transcription

```text
                                      along the flow axis

  Replay mode                         replays a recorded measure from the disk

  Saving mode                         save the past, record the future (manual trigger)


  Memory/Files

  Internal memory size                without package "advanced Record"
                                      1000 profiles

                                      with package "advanced Record" installed
                                      64'000 profiles, 65'536 blocks



  Configuration parameters            without package "advanced Record"
                                      1 saved configuration

                                      with package "advanced Record" installed
                                      9 saved configurations with description

  Data file format                    binary
                                      ASCII
                                      ASCII statistical data
  Environment

  Power supply                        110 - 220 VAC, 50 - 60 Hz

  Host PC Operating system            Windows® XP

  Communication                       via USB full speed, Connector type B

  US interface                        US probe In/Out, BNC
                                      Echo, (max 0.7 Vp), output impedance of 50 ohm
                                      PRF, TTL low level pulse of 100 ns at each emission

  External trigger input              TTL level, pull up 330 ohm

  Temperature                         5 - 35 degrees

  Sizes                               235 x 98 x 347 cm

  Weight                              3 Kg
  Options

  software packages                   variable frequency
                                      variable gates
                                      additional compute mode
                                      variable resolution
                                      advanced recording features
                                      variable TGC
                                      ultrasonic field measurement
                                      sound velocity measurement
                                      advanced Trigger
```
