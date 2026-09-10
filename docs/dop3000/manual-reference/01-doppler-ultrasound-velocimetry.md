# 1. Doppler ultrasound velocimetry

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 7-12.

---

<!-- source-pdf-page: 7 -->
## Source PDF page 7

## 1 Doppler ultrasound velocimetry

Doppler ultrasound velocimetry, was originally applied in the medical field and dates back more than 30 years. The use of pulsed emissions has extended this technique to other fields and has opened the way to new measuring techniques in fluid dynamics. The term "Doppler ultrasound velocimetry" implies that the velocity is measured by finding the Doppler frequency in the received signal, as is the case in Laser Doppler velocimetry. In fact, in ultrasonic pulsed Doppler velocimetry, this is never the case. Velocities are derived from shifts in positions between pulses, and the Doppler effect plays a minor role.

### 1.1 Doppler effect

The Doppler effect is the change in frequency of an acoustic or electromagnetic wave resulting from the movement of either the emitter or receptor.

Let us consider an ultrasonic transducer which emits waves of frequency fe and remains constant in a medium where the speed of sound is c. A receptor, or target, in the medium moves with a velocity v. By convention, v is considered negative when the target is moving toward the transducer. If the trajectory of the target forms an angle θ1 with respect to the direction of propagation of the ultrasonic wave, the frequency of the waves perceived by the target will be:

#### Equations reconstructed from the page image

*Frequency perceived by the moving target:*



$$
f_t = f_e - \frac{f_e v\cos\theta_1}{c}
$$

#### Figures and in-context visual analysis

**Reconstructed caption:** Bistatic emitter-receiver geometry.



**In context:** The emitter and receiver view the moving target from different directions, defining θ1 and θ2. The geometry supplies the two cosine terms in the general Doppler-shift equation; the monostatic case collapses to the familiar factor of two.

---

<!-- source-pdf-page: 8 -->
## Source PDF page 8

If the acoustic impedance of the target is different from that of the surrounding medium, the waves will be partially reflected. The target acts as a moving source of ultrasonic signals. The frequency of the waves reflected by the target, as measured by a stationary receiver, is:

As the velocity of the target is much smaller than the speed of sound (v << c) it is reasonable to neglect the second order terms. The difference between the emitted and received signals, which is known as the Doppler frequency shift, is then expressed by:

If the same transducer is used for receiving the signals the above equation becomes (Doppler equation):

### 1.2 Pulsed Doppler ultrasound

In pulsed Doppler ultrasound, instead of emitting continuous ultrasonic waves, an emitter sends a short ultrasonic burst periodically and a receiver continuously collects echoes issued from targets that may be present in the path of the ultrasonic beam. By sampling the incoming echoes at the same time relative to the emission of the bursts, the shift of positions of scatterers are measured. Let's assume the case illustrated in the figure below, where only one particle is in the ultrasonic beam. From the knowledge of the time delay Td between an emitted burst and the echo reflected by the particle, the depth p of this particle can be computed by:

where c is the sound velocity of the ultrasonic wave in the liquid.

#### Equations reconstructed from the page image

*Frequency received after reflection:*



$$
f_r = f_t + \frac{f_t v\cos\theta_2}{c}
$$

*General Doppler frequency shift:*



$$
f_d = \frac{f_e v\left(\cos\Theta_1-\cos\Theta_2\right)}{c}
$$

*Monostatic Doppler equation:*



$$
f_d = \frac{2f_e v\cos\theta_1}{c}
$$

*Target depth from round-trip delay:*



$$
P = \frac{cT_d}{2}
$$

---

<!-- source-pdf-page: 9 -->
## Source PDF page 9

If the particle is moving at an angle θ in relation to the axis of the ultrasonic beam, its velocity can be measured by computing the variation of its depth between two emissions separated in time by Tprf:

The time difference (T2-T1) is always very short, most of the time less than a microsecond. It is advantageous to replace this time measurement by a measurement of the phase shift of the received echo.

where fe is the emitting frequency. With this information the velocity of the target is expressed by:

This last equation gives the same result as the Doppler equation but one should always be aware that the phenomena involved are not the same. Let's assume that the particles are randomly distributed inside the ultrasonic beam. The echoes returned by each particle are then combined together in a random fashion, giving a random echo signal. Hopefully, a high degree of correlation exists between different emissions. This high degree of correlation is highlighted in all digital processing techniques used in Signal Processing's Ultrasonic Doppler velocimeter to extract information, such as the velocity.

### 1.3 Advantages and limitations

The main advantage of pulsed Doppler ultrasound is its ability to offer spatial information associated with velocity values. Unfortunately, as the information is available only

#### Equations reconstructed from the page image

*Inter-pulse displacement:*



$$
P_2-P_1 = vT_{\mathrm{prf}}\cos\theta = \frac{c}{2}(T_2-T_1)
$$

*Echo phase shift:*



$$
\delta = 2\pi f_e(T_2-T_1)
$$

*Velocity from phase shift or Doppler frequency:*



$$
v = \frac{c\delta}{4\pi f_e\cos\Theta\,T_{\mathrm{prf}}} = \frac{cf_d}{2f_e\cos\Theta}
$$

#### Figures and in-context visual analysis

**Reconstructed caption:** Pulsed range and displacement geometry.



**In context:** Two emissions locate a particle at P1 and P2. The depth change ΔP is the beam-axis component of displacement, so dividing by the pulse interval and correcting by cos θ gives the particle velocity.

---

<!-- source-pdf-page: 10 -->
## Source PDF page 10

periodically, this technique suffers from the Nyquist theorem. This means that a maximum velocity exists for each pulse repetition frequency (PRF):

If the measured velocity is higher than this maximum velocity, a phenomena named aliasing will appear. In such a situation, all Doppler frequencies above the half of the sampling frequency (fprf =1/Tprf), are folded back in the low frequency region or aliased. The figure below illustrates the relationship between the real frequency and the measured frequency.

2

1

3

At point 1 , the real Doppler frequency is below the Nyquist limit (Fprf/2), so the measured frequency is equal to the real frequency. At point 2 , the real Doppler frequency is much above the Nyquist limit. Point 2 is then backfolded to point 3 , which gives a negative velocity. This negative frequency is equal to the real frequency from which the sampling frequency is substracted. For an analog signal it is possible to avoid aliasing by filtering the signal before sampling it in order to remove all the frequencies above the Nyquist limit (FPRF/2). Unfortunately for pulsed Doppler ultrasound only samples are available and therefore it is not possible to remove the aliasing. The only solution is to adapt the sampling rate or the pulse repetition frequency to the Doppler signal that has to be measured.

**Note:** An easy way to check the presence of aliasing is to examine the evolution of the measured Doppler frequency when changing the pulsed repetition frequency.

In addition to the maximum velocity limitation, there is a maximum depth at which a velocity may be measured. This limit is determined by the time needed for the ultrasonic signal to travel from the transducer to the target and back. This time is determined by the

#### Equations reconstructed from the page image

*Maximum unaliased velocity:*



$$
v_{\max}=\frac{c}{4f_e\cos\Theta\,T_{\mathrm{prf}}}
$$

#### Figures and in-context visual analysis

**Reconstructed caption:** Aliasing transfer characteristic.



**In context:** The sawtooth maps real frequency to the measured interval bounded by ±FPRF/2. Frequencies outside that Nyquist interval fold back, explaining the discontinuous apparent velocity jumps discussed in the text.

---

<!-- source-pdf-page: 11 -->
## Source PDF page 11

pulse repetition frequency (PRF) of the ultrasonic pulses. This gives a maximum depth equal to:

Reducing the PRF (increasing Tprf) will increase the maximum measurable depth, but will also reduce the maximum Doppler frequency which can be measured. The maximum velocity and depth which may be measured are thus related according to the following equation:

At any given instant, an echo signal can come from many different depths, corresponding to echoes from previously emitted signals. The presence of several acoustic interfaces also causes several reflections which can cause a false determination of the target depth. Nevertheless, if the PRF is sufficiently low (a few kHz), the attenuation of previously emitted pulses will render them indiscernible. The same goes for reflected signals. With a large increase in the PRF, pulsed Doppler ultrasound can approach the properties of continuous wave Doppler, with a loss of axial resolution but no maximum velocity limitation.

#### Equations reconstructed from the page image

*Maximum unambiguous depth:*



$$
P_{\max}=\frac{T_{\mathrm{prf}}c}{2}
$$

*Depth-velocity trade-off:*



$$
P_{\max}V_{\max}=\frac{c^2}{8f_e}
$$

---

<!-- source-pdf-page: 12 -->
## Source PDF page 12
