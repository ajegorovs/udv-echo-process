# 7. Measuring the sound speed

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 43-44.

---

<!-- source-pdf-page: 43 -->
## Source PDF page 43

## 7 Measuring the sound speed

The DOP3000 allows to measure the sound speed in a liquid by measuring with precision the time that is taken by an ultrasonic burst to propagate over a define distance.

### 7.1 Preparing the measurement

Before using the software, you should first install the probe as defined in the figure below. The probe must be placed at a defined distance (Dmes) from a reflector. The reflector must be a plan surface, placed perpendicularly to the US beam axis of the probe. If you plan to use the transmission mode instate of the echo mode, the reflector will be replaced by an other transducer operating at the same frequency.

Dmes

Be sure that the probe is completely immerged. The distance between the reflector and the probe surface (Dmes), which is named "Reference distance" in UDOP, must be in the range 15 to 50 mm and must be measured with precision as any error in the measured distance will be directly transferred to the sound speed measured value.

### 7.2 Measuring the sound speed

Go in the menu "Tools" and click on the button named "Measure sound speed". The velocimeter opens a new panel in which you must enter an expected sound speed value and the reference distance Dmes. The expected sound speed value helps UDOP software to find a correct set of measuring parameters. If the entered expected value is to far away from the real value, UDOP software will not be able to find a correct set of parameters and therefore no sound speed measurement will be possible.

The parameters are selected in order to have a clear echo coming from the reflector. UDOP adapts the parameters in order to achieve this task. If you prefer to select by your self the parameter, you can by-pass the calibration procedure and keep the current set of parameters. To do this click on the button named "Here". If you would like that UDOP select the parameters for you click the button "Continue".

#### Figures and in-context visual analysis

**Reconstructed caption:** Sound-speed measurement fixture.



**In context:** The photograph shows the controlled path used to obtain a known travel distance. Combining this geometry with the measured time of flight yields the medium's sound speed.

---

<!-- source-pdf-page: 44 -->
## Source PDF page 44

**Note:** A long burst gives better results than a short burst. So try to use the longest. (32 cycles),

UDOP than shows the portion of the echo profile that must correspond to the echo coming from the reflector. If this echo is clear and good enough, a simple click on the button "show measures" allows to see the measured values and its statistics.

A click on the button "Keep and exit" ends the measurement of the sound speed and keeps the measured value as the current sound speed value.
