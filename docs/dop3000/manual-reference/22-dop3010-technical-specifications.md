# 22. DOP3010 technical specifications

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 123-126.

---

<!-- source-pdf-page: 123 -->
## Source PDF page 123

#### Layout-preserving transcription

```text
22 DOP3010 technical specifications
Emission

Emitting frequency                  variable between 0.45 MHz and 10.5 MHz, with a resolution of 1
                                    kHz

Emitting power                      3 levels. Approximative instantaneous maximum power for
                                    setting:
                                    low = 0.5 W, medium= 5 W, high= 35 W

Number of emitted cycles            2 to 32, step of 2 or 4 cycles

Pulse repetition frequency          selectable values between 100'000 μs and 64 μs, step of 1 μs
Reception

Number of gates                     variable between 1000 and 4, step of 1 gates

Position of the first gate          movable by step of 1 mm but not earlier than the end of the
                                    emitted burst

Amplification (TGC)                 amplification range from -40 to 40 dB
                                    uniform
                                    slope mode
                                      exponential amplification between two defined
                                      depth values.
                                    custom mode
                                      user's defined values between -40dB and +40dB in
                                      cells; variable number (from 1 to 1024), size and
                                      position of the cells.
                                    automatic computation

Sensitivity                         > -100 dBm
Sampling volume

lateral size                        defined by the acoustical characteristics of the transducer.

longitudinal size                   defined by the burst length and/or a user's selectable internal
                                    filter. Available values:
                                    3.9, 2.9, 1.3, 1.1, 0.8, 0.7 mm
                                    (c=1500 m/s ,defined at 50% of the received signal level)



Display resolution:                 distance between the center of each sampling volume
                                    selectable between 0.166 and 20 μs, step of 0.166 μs.

Velocity resolution                 1 LSB, Doppler frequency given in a signed byte format.
                                    Depends on velocity scale and emitting frequency
Ultrasonic processor

Doppler frequency                   computation based on a correlation algorithm

Wall filter                         stationary echoes removed by IIR high-pass filter 2nd order

Emissions per profile               between 512 and 8, any values
```

---

<!-- source-pdf-page: 124 -->
## Source PDF page 124

#### Layout-preserving transcription

```text
  Detection level                    5 levels of the received Doppler energy may disable the
                                     computation

  Acquisition time per profile       minimum: about 2-3 ms

  filters on profiles                moving average:
                                      based on 2 to 1000 profiles
                                      zero values included or rejected
                                     median, based on 3 to 32 profiles

  Velocity scale                     variable positive and negative velocity range, movable origin.

  Maximum velocity                   Without aliasing correction, bi-directional
                                     0.5 MHz 11.72 m/s
                                     1 MHz5.86 m/s
                                     2 MHz2.93 m/s
                                     4 MHz1.46 m/s
                                     8 MHz0.73 m/s
                                     10 MHz0.59 m/s
                                      (twice if uni-directional)

                                     With aliasing correction enabled, no limit (depends on flow
                                     conditions and noise level)

  Compute and display                velocity profile
                                     Doppler energy
                                     echo profile
                                     velocity profile with echo profile or Doppler energy
                                     velocity profile with v(t) of a selected gate
                                     power spectrum of one selected gated
                                     velocity profile and time-space
                                     velocity profile and flowrate

  Cursor                             4 available cursors in tracking mode (follow the displayed
                                     curve). Statistical values available (Mean, standard deviation,
                                     minimum, maximum)

  External Trigger                   by external signal, change in the logic state (TTL/CMOS level)
                                     automatic record capability
                                     Trigger delay from 0 ms to 32s, step of 1 ms

  Velocity component                 automatic computation of the projected velocity component
                                     along the flow axis

  Replay mode                        replays a recorded measure from the disk

  Saving mode                        save the past, record the future (manual trigger)

  Additional tools                   measurement of the sound velocity
                                     automatic detection of artefacts
                                     measurement of the ultrasonic field
                                     raw data acquisition (15'000 demodulated IQ values)
  Multiplexer

  Number of channels                 10

  Configuration parameters           all channels have their own set of parameters
```

---

<!-- source-pdf-page: 125 -->
## Source PDF page 125

#### Layout-preserving transcription

```text
Switching time                       0.1 ms

Contact resistance                   0.2 ohm

Switching rate                       recommeded: 10 Hz

Life expectancy                      109 cycles


Memory/Files

Internal memory size                 2'097'152 profiles, divided in blocks from 1 to 65536 blocks

Configuration parameters             9 saved configurations with description

Data file format                     binary
                                     ASCII
                                     ASCII statistical data
Environment

Power supply                         110 - 220 VAC, 50 - 60 Hz

Host PC Operating system             Windows® 98, XP, Vista, 7

Communication                        via USB full speed, Connector type B

US interface                         US probe In/Out, 10 BNC (1 for each channel)
                                     receivers probes used in UDV 2D/3D, 3 BNC
                                     emitted burst, output, BNC
                                     Echo, (max 0.7 Vp), output impedance of 50 ohm, BNC
                                     PRF, TTL low level pulse of 100 ns at each emission, BNC

External trigger input               TTL level, pull up 330 ohm

Temperature                          5 - 35 degrees

Sizes                                235 x 98 x 347 mm

Weight                               3 Kg
Options

UDV 2D/3D software package
```

---

<!-- source-pdf-page: 126 -->
## Source PDF page 126
