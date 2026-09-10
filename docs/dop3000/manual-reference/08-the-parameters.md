# 8. The parameters

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 45-56.

---

<!-- source-pdf-page: 45 -->
## Source PDF page 45

## 8 The parameters

The velocimeter is controlled by a defined number of parameters which are user selectable for most of them. Correct values of these parameters are of prime importance.The following chapter describes the meaning of these parameters and their influences on the measured values. The velocimeter contains a default setup, named "Default parameters" which can not be changed, and which guarantees that the velocimeter will work correctly. It is highly recommended to always start from this setup any measurements on new facilities.

**Note:** Without the additional software package "Advanced recording features" UDOP always recalls at power up the parameters that were in used just before closing UDOP.

### 8.1 The Pulse Repetition Frequency (PRF)

The pulse repetition frequency or PRF determines the maximum measurable depth as well as the maximum Doppler frequency which can be measured unambiguously. The maximum depth is simply given by half the distance covered by the ultrasonic burst when it travels in the medium during a time equal to the time between two emissions. As the PRF is nothing else than the sampling rate of the ultrasonic echo, the Nyquist limit defines the maximum Doppler frequency shift that can be measured unambiguously. Therefore the PRF defines the maximum velocity for a given emitting frequency. As a consequence, both limits, the maximum velocity and the maximum depth, are linked together as expressed below:

where Pmax is the maximum measurable depth, Vmax the maximum measurable velocity, fe the emitting frequency and C the speed of sound in the medium.

How to choose a correct PRF value

The choice of a PRF value should normally be based on the velocity values that have to be measured rather than on the depth that has to be reached. Whenever possible, one should try to select a value which does not induce aliasing. The best way to select a correct value is to start with a high value (near the maximum) and to reduce this value until at least 50% of the velocity scale is covered. The desired analyzed depth can be then adapted by changing the resolution, the position of the first gate or the number of gates.

#### Equations reconstructed from the page image

*Linked depth and velocity limits:*



$$
P_{\max}V_{\max}=\frac{c^2}{8f_e},\qquad P_{\max}=\frac{C}{2F_{\mathrm{PRF}}},\qquad V_{\max}=\frac{F_{\mathrm{PRF}}C}{4f_e}
$$

---

<!-- source-pdf-page: 46 -->
## Source PDF page 46

**Note:** Due to internal computation time, the maximum depth can never reach the depth computed by the above formula, based on the sound speed and the PRF. Its value is always a little bit lower.

Never apply a filter during the selection process of a PRF. Any aliasing that can ! appear will be masked by the moving average filter.

### 8.2 The velocity scale factor

The DOP3000 allows to measure velocities of liquids coming towards or going away from the transducer. By definition, the velocity is positive if the particle goes away from the transducer and negative if it goes in the other direction. The maximum velocity that can be measured without inducing aliasing is a function of three parameters, which are:

the emitting frequency; The more the emitting frequency is high, the more the Doppler frequency shift is high. Therefore an increase in the emitting frequency will decrease proportionally the maximum measurable velocity.

the speed of sound in the liquid; The speed of sound is the key factor that converts the Doppler frequency shift in velocity. There is a direct proportionality between these two parameters.

the pulse repetition frequency; The pulse repetition frequency defines the maximum measurable Doppler frequency in accordance to the Nyquist limit. Therefore, the higher the PRF is, the higher the Nyquist limit is and the higher the maximum measurable velocity is. Unfortunately, the PRF defines also the maximum measurable depth.

The ultrasonic processor of the DOP3000 outputs the velocity values in a signed byte format, which allows 256 different velocity values. The range of velocities covered by these 256 values can be adapted by the user in order to cover a portion of the maximum measurable Doppler frequency shift which is defined by the Nyquist limits or PRF/2. This portion of velocity range can correspond to the entire range (value of 1) or 10% of the entire range (value of 0.1).

### 8.3 Position of the first gate

When the first gates are close to the surface of the transducer, the burst duration and the ringing of the ceramic do not allow any measurement in these gates due to saturation of the electronic receiver.This can be visualized in the display of the received echoes, where the level of the signal at low depths (close to the transducer) is saturated (values above 2000). This saturation is normal and can not be avoided.

---

<!-- source-pdf-page: 47 -->
## Source PDF page 47

The position of the first measurable gate depends on the emitting frequency, the burst length, the emitting power, the amplification level and the ultrasonic probe connected to the instrument. Its minimum value is around 3 millimeters. The position of the first gate can be changed by clicking on the depth axis and moving the mouse left or right. If the assisted mode is active, a change in the measured depth range may induce also a change the measurable velocity range.

**Note:   The origin of the measured depth is the surface of the transducer.**

The position of the first gate can only be moved if the "Extended number of gates" software package is installed. In such a case two arrows appear on the legend of the depth scale.

### 8.4 The resolution and burst length

The DOP3000 defines the resolution as the distance between the center of adjacent sampling volumes and NOT the thickness of the sampling volume. In ultrasonic Doppler velocimetry, the shape and lateral sizes of the sampling volumes (measured perpendicularly to the ultrasonic beam axis) are defined by the geometry of the ultrasonic beam. The longitudinal size of the sampling volumes, or their thickness, is defined by the burst length and/or the bandwidth of the electronic receiving unit.

The DOP3000 has 6 different bandwidth values, covering a range from 50 kHz to 300 kHz. This defines a longitudinal dimension of the sampling volume from about 0.64 mm to 3.19 mm in water. These different bandwidth act as a spatial filter. If the duration of the emitted burst is longer than the value associated to the bandwidth, the longitudinal dimension of the sampling volume is determined by the burst length.

It may often appear that the selected resolution implies an overlapping of the sample volume. This is the case when the resolution is lower than the thickness of the sampling volume. This always appears for all resolution below 0.64 mm.

When the selected resolution corresponds to a distance longer than the longitudinal dimension of the sampling volume, the sampling volumes do not touch each other any more and some non measured spaced are present between the sampling volumes.

#### Figures and in-context visual analysis

**Reconstructed caption:** Resolution compared with sample-volume thickness.



**In context:** When the chosen gate spacing is smaller than the physical sample volume, adjacent measurements overlap; when it is larger, gaps appear. The figure explains why display resolution is not identical to acoustic resolution.

---

<!-- source-pdf-page: 48 -->
## Source PDF page 48

Note that the borders of the sampling volumes are not as well defined as represented in the figure above. The borders increase and decrease "slowly" due to the finite bandwidth of the receiver.

The ultrasonic beam produced by the transducer does not have a constant diameter along the analyzed depth. The consequence of the divergence of the ultrasonic beam is that the lateral dimensions of the sampling volumes are not the same for all the sample volumes. Generally their lateral dimensions increase when the measured depth increases. The rate of this increase depends on the frequency and dimensions of the transducer.

The thickness of the sampling volume is displayed in the "Operating parameters" window. If the sampling volumes overlapped each other an indication is displayed.

**Note:** If the optional software package "Extended resolution" is not installed only two resolutions are available and the bandwidth of the electronic receiving unit is fixed.

### 8.5 The number of gates

The DOP3000 can measure simultaneously up to 1000 gates. The number of gates that can be measured depends on the selected PRF, the position of the first gate and the selected resolution. The user has the choice to let the instrument select automatically the number of gates in order to cover the selected depth or to fixe it. In such a case t he position of the first gate and the number of gates define the measuring range and therefore the analyzed depth.

**Note:** If the optional software package "Extended number of gates" is not installed the DOP3000 the maximum number of gates is limited to 100 and is not user's selectable.

### 8.6 The sensitivity

The algorithm used to measure the Doppler frequency computes the mean frequency of the Doppler spectrum. When the Doppler energy decreases, the mean value become more and more unstable due to the noise included in the spectrum. In order to avoid the apparition of random values on the screen, the DOP3000 computes also the level of Doppler energy received and allows the user to cancel the computation of the Doppler frequency if the level of the Doppler energy is below a user's defined value. In such a case the canceled values are replaced by zero values.

---

<!-- source-pdf-page: 49 -->
## Source PDF page 49

The sensitivity parameter contains 5 different values, which define the level below which the computation is canceled. As it can be sometimes useful to accept the computation of the mean Doppler frequency in presence of very low Doppler energy, two levels named "Very high" and "High" can be used in such a situation. When "High" is selected, some noise may appear on the screen. When "Very high" is selected it is normal to have noise displayed on the screen.

The choice of a sensitivity value do not introduce any bias if the Doppler energy is high.

```text
The sensitivity parameter can be used to obtain information on the quality of the
measured values. No changes should result if the sensitivity parameter is modified. Any
changes will mean that the level of the Doppler energy is too low. In such a case, to
correct this situation, the following options should be investigated:
           -   a modification of the emitted power;
           -   a modification of the amplification (TGC);
           -   an increase in the amount of particles contained in the liquid.
```

### 8.7 The number of emissions per profile

The measurement of the Doppler frequencies is based on the correlation that exists between different emissions. As each emission can be seen as a particular realization of a random process, the more samples are available, the lower the variance of the estimated quantity will be. This is the case for the mean Doppler frequencies, which are first moment orders of Doppler spectrum. The algorithm used to estimate the Doppler frequency is based on the assumption that the particles that generate the echoes during the measurement of the Doppler frequency remain inside the ultrasonic beam and their velocities are constant. For low velocities in steady flows this assumption is valid, but for transient ones, with high velocities, a compromise has to be taken between the quality of the estimation (minimum variance) and the measuring time. The number of emissions per profile should be selected according to the type of flow investigated and to the width of the ultrasonic beam. For low velocities in steady flows, a high number will decrease the variance and therefore should be selected. For high velocities in unstationary flows this number should be adapted to the degree of variation of the velocities versus time.

Reducing the number of emission per profile increases the acquisition rate. By means of a filter, like the moving average the noise can be reduced.

---

<!-- source-pdf-page: 50 -->
## Source PDF page 50

### 8.8 The time between profiles

The number of emissions per profile defines also, with the PRF value, the time necessary to measure a profile. This time is defined by the following relation:

T profile ≈ T tran + T PRF · ( N Stb + N PRF )

where TPRF is the period of the pulse repetition frequency, Ttran a time lapse used to transfer data (see below), NPRF the number of emissions per profiles and NStb, a fixed number of emissions used for internal computations, which is equal to 16. The above equation gives an approximate value. The additional time Ttran, which may fluctuate, corresponds to the mean time used to transfer the measured data from the internal ultrasonic processor to the internal memory. This time may occasionally vary quite a lot due to the Windows environment.

In order to reduce the jitter in the transfer time Ttran it is highly recommended to ! run only the UDOP program and to not use the multi tasking capability of the Windows environment.

If the assisted mode is selected, the UDOP software try to find the best compromise between the PRF, the number of emissions per profile, the velocity scale, and the requested acquisition rate. The time stamp attached to each profile is the time measured when the profile is transferred from the ultrasonic processor to the internal memory. This time, measured with a resolution of 100 microseconds, is unaffected by the operating system.

The DOP3000 displays continuously the mean value of the time between profiles in the status window. This mean value is based on the last 8 previous profile. The maximum and minimum values are displayed beside the mean value in the status window.

Mean          Minimum            Maximum

If the acquisition rate is to high, the label "Time between profiles" is displayed in red. The indicates that the time between profiles is not constant. Different solution can be applied to correct this situation: - reduce the size of the main UDOP window - reduce the number of gates

#### Figures and in-context visual analysis

**Reconstructed caption:** Measured time-between-profiles status.



**In context:** The status field reports the actual inter-profile interval and its observed range, which may differ slightly from the requested value because acquisition and transfer take time.

---

<!-- source-pdf-page: 51 -->
## Source PDF page 51

- reduce the number of curves displayed
- Increase the time between profiles

### 8.9 The emitting frequency

The choice of an emitting frequency depends on different factors which are: - the desired size of the sampling volume; the emitting frequency contributes to the definition of the longitudinal dimension of the sampling volume. As this dimension is linked to the duration of the burst, for a given number of cycles in the burst, a higher emitting frequency will give a better resolution. - the attenuation of the ultrasonic signal; the attenuation of ultrasonic waves depends on their frequencies. Low frequencies are less attenuated than high frequencies. The attenuation coefficient may vary quite a lot and depends on the material. - the maximum measurable velocity; the maximum measurable velocity is inversely proportional to the emitting frequency. - the backscattered energy; the ultrasonic energy backscattered by the particles depends on the ultrasonic frequency. High ultrasonic frequencies backscatter more energy than low ultrasonic frequencies All the above comments should be considered when selecting the emitting frequency.

If the optional software package "variable ultrasonic emitting frequency" is installed, the DOP3000 can be operated at any emitting frequencies between 0.45 MHz and 10.5 MHz with a resolution of 1 kHz. If not installed the emitting frequency is fixed.

### 8.10 The emitting power

The emitted ultrasonic power has to be selected in order to receive enough backscattered energy from the particles and to avoid as much as possible saturation in the receiver stage. The display of the echo profile may be used to verify this point. Try whenever possible to avoid a high emitting power. A high emitting power induces more ringing in the transducer and more dissipated energy. It is generally better to increase the amplification (TGC) in state of increasing the emitting power. The DOP3000 can use 3 different emitting powers.

---

<!-- source-pdf-page: 52 -->
## Source PDF page 52

### 8.11 Definition of the amplification level (TGC)

Correct values of the amplification level are important. A to high level may induce saturation in the receiver stage of the DOP3000, which induces wrong measurement values. The amplification level can be defined by four different methods.

The first one simply defines a constant value in all the measuring range The second one, which is named the slope method, defines the amplification level at two particular depths, named "Start value" and "End value", which are the first and last displayed depth. Between these depths, the amplification level vary exponentially.

The third one, is based on the information issued from the assisted mode. The TGC is automatically defined in order to establish some kind of optimum amplification curve.

The fourth one, which is named the custom method, allows to define the amplification level in user's defined regions, which can be placed anywhere in the measuring range. The number of possible regions depends on measuring range.

The value of the amplification level displayed by the instrument gives the increase of the signal level, from the transducer to the input of the internal A/D converter. 256 different levels of amplification are available, covering a range of 80 dB.

The amplification level should be selected on the basis of the modulus of the echo profile. This display shows the intensity of the received echoes which are processed by the internal ultrasonic processor. Any saturation of the receiver stage is seen on that display by a region of maximum values which are independent of the flow regime and conditions. The user should adapt the amplification level or TGC in order to remove all these fixed overflow values.

**Note:** If the amplification level has to be reduced and if the liquid investigated does not attenuate to much the ultrasonic waves, it is recommended to decrease the emitting power. This reduces the intensity of the received echoes and any undesirable effects, such as the ringing inside the transducer.

---

<!-- source-pdf-page: 53 -->
## Source PDF page 53

The 2 figures below show 2 different situations. The figure A shows a situation where a reduction of the amplification level is absolutely necessary. In Figure B the amplification level is correct.

A                               B

The saturation appearing at depths located just after the surface of the transducer is normal and can not be removed. This saturation is generated by the ringing effects of the transducer following the emission. The depths affected by this phenomena depend on the emitted burst emitted (frequency, burst length) and on the transducer. At these depths correct measurements are not possible.

#### 8.11.1 Uniform amplification

In this mode the amplification level is the same for all depths. This mode is easy to use and can be used for instance when the analyzed range is small. When measuring profiles in liquid for which the attenuation of ultrasonic waves is small this method may also be convenient.

#### 8.11.2 The Slope method

In this mode the amplification varies exponentially between two fixed depths which are the first and the last displayed depth. At these two particular depths, named "Start value" and "End value", the amplification level can be selected.

The slope method is only available is the optional software package "Variable TGC" is installed.

#### 8.11.3 The Custom method

In this mode the amplification curve is defined by a series of contiguous cells, inside which the amplification level is uniform.

The position and size of a cell are defined in the velocity or in the echo profile by placing two cursors. The left mouse button is associated to the start of the cell (red cursor) and the right mouse button to the end of the cell (blue cursor). The defined cell appears in yellow inside the profile. When the cell is defined a TGC value can be associated to it by

#### Figures and in-context visual analysis

**Reconstructed caption:** Echo amplitude versus depth.



**In context:** Peaks locate strong reflectors along the beam. The trace is used to tune sensitivity and time-gain compensation while keeping echoes within the measurable range.

**Reconstructed caption:** Saturated echo amplitude versus depth.



**In context:** Repeated clipping at the upper amplitude limit indicates excessive gain. Saturation destroys relative amplitude information and can degrade velocity estimation.

---

<!-- source-pdf-page: 54 -->
## Source PDF page 54

entering a value in the edit zone named "cell value"

The portion of the profile which define a cell is displayed in yellow. The resulting custom TGC amplification curve is displayed on the right side of the screen

**Note:** All the custom TGC amplification values are saved with the parameters when the user records a measurement on a file. These values are also saved with the current parameters. Defining an other TGC amplification curve does not destroy the values defined in the custom mode.

The slope and custom method is only available if the optional software package "Variable TGC" is installed.

### 8.12 The Doppler angle

The velocimeter always measures the projection of the real velocity vector on the ultrasonic beam axis and gives therefore only one component of the velocity vector. It can happen sometimes that the direction of the real velocity vector is known, as in the case of flows in long tubes where the direction of the velocity vector is parallel to the axis of the tube. In such a case, it is possible and useful to compute directly the module of the velocity vector by using the Doppler angle. The Doppler angle (named θ in the next figure) is the angle between the axis of the ultrasonic beam and the direction of the real velocity vector.

The DOP3000 uses the simple formula below to convert all velocity components measured in the direction of the ultrasonic beam (VUS) in real velocity values (Vreal). To select this computation mode, simply enter an non zero value.

Vus Θ Vreal

### 8.13 The speed of sound

The knowledge of the speed of sound in the medium is necessary to transform the Doppler frequency shifts in mm/s, and the time of flight of the ultrasonic waves in millimeter. A good knowledge of the sound velocity in the medium is necessary to obtain good quantitative measurement values, as all errors in this parameter are directly

#### Equations reconstructed from the page image

*Real velocity from the measured beam-axis component:*



$$
V_{\mathrm{real}}=\frac{V_{\mathrm{us}}}{\cos\theta}=\frac{f_dC}{2\cos\theta\,f_e}
$$

#### Figures and in-context visual analysis

**Reconstructed caption:** Doppler-angle correction geometry.



**In context:** The instrument measures Vus along the beam. Dividing by cos θ reconstructs the known flow-direction magnitude Vreal; errors grow rapidly as θ approaches 90 degrees.

---

<!-- source-pdf-page: 55 -->
## Source PDF page 55

transferred to the measured values. Tables exist for a lot of liquids. One may find in the annex of this manual such a table.

If the speed of sound is unknown, the DOP3000 offers in option the possibility to measure it with a special software. The accuracy of the measured values are in the order of 1-2%. This software is available under the tools menu When measuring through a wall or when using a wave guide, it may be necessary to take into account the sound speed inside the wall and inside the coupling medium. This is possible when the assisted mode is disable. The operating parameters table contains a button named "use US coupling parameters" that allows to enter the sound velocity and the thickness (or length) of the wall and of the coupling medium. If these parameters are used (button checked), the first measuring gate is really placed inside the liquid at a correct distance from the wall.

---

<!-- source-pdf-page: 56 -->
## Source PDF page 56
