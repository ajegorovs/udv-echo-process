# 4. Using the velocimeter

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 21-30.

---

<!-- source-pdf-page: 21 -->
## Source PDF page 21

## 4 Using the velocimeter

This chapter is intended to explain how to use DOP ultrasonic Doppler velocimeter. Before using the instrument be sure that the USB software driver is already installed. If the driver is not installed properly, UDOP will not detect any instrument and will start in simulation mode.

### 4.1 Installation of the ultrasonic probe

The DOP emits and receives the ultrasonic echoes on the same BNC connector. Probes can be connected or removed without turning off the power line of the velocimeter.

**Caution:** Ultrasonic probes are fragile. They must be handled with care and they must not receive any shocks. The probe support must not induce mechanical stress especially to the front surface of the probe.

Whenever possible it is always better to put the probe directly in contact with the liquid. Crossing interfaces or walls induces reflections which reduce the amount of ultrasonic power injected in the liquid and may disturb the ultrasonic field (see the chapter «Influences of interfaces»).

The probe should be mounted on a rigid support which should have some degrees of freedom in order to select an appropriate position, but it may be useful to start by handling the probe by hand in order to find a good position.

When positioning the probe the points below should be taken into account:

- a good position is a position which generates the minimum stationary echoes; - when crossing interfaces, the angle between the probe axis and the surface of the interface must take into account the maximum refraction angle. This angle is defined by the ultrasonic properties of the different medium in presence; - vibrations of the probe support should be avoided; - it is absolutely necessary to remove of any gas layers or bubbles when coupling the probe; the attenuation of ultrasonic waves in gas at the working frequencies is so high that most of the emitted energy is dissipated in the gas. - be sure that the front face of the probe is always in contact with the liquid or the coupling medium.

---

<!-- source-pdf-page: 22 -->
## Source PDF page 22

- always try to avoid to be perpendicular to an interface. Being just only a few degrees away from the perpendicular reduces stationary echoes that may appear between the transducer and proximate walls.

When the ultrasonic probe is directly in contact with the liquid it is not necessary to use any coupling medium. If the ultrasonic waves have to cross a solid interface it is absolutely necessary to use a coupling medium, like the ultrasonic gel delivered with the instrument. It is not necessary to put the probe in contact with the interface. The coupling medium, which can be an ultrasonic gel, will guarantee a path for the ultrasonic waves. The coupling medium should be put in enough quantity. It should completely cover the extremity of the probe.

Small gas bubbles may appears after a certain time on the surface of the probe especially when the liquid contains a lot of gas dissolved in it. These bubbles should be removed.

### 4.2 Defining the operating parameters

The quality of the measurements depends on the choice of the parameters values. Unfortunately in ultrasonic Doppler velocimetry the most important parameters are linked together, like the maximum measurable depth and the maximum velocity.

UDOP allows to define the operating parameters by two methods. The first one, which is named "the assisted mode" allows to bypass the introduction of the ultrasonic parameters and allows to enter directly the application parameters which are the velocity range and the depth range. A quality factor parameters is used to realize a kind of compromise between the acquisition rate and the standard deviation of the measured values.

Most of the value are entered by means of input button such the one illustrated in the figure below:

If the edit zone is used to enter a new value, the new number must be validated by the pressing the carriage return on the keyboard. The sliding bar also allows to change the value. The big one covers all the possible range, the small one only a portion around the current value.

#### Figures and in-context visual analysis

**Reconstructed caption:** Maximum-depth input control.



**In context:** The 'To' field sets the end of the displayed/measured depth interval. Its value works with the first-gate position, resolution, and number of gates.

---

<!-- source-pdf-page: 23 -->
## Source PDF page 23

It is not possible to give a general rule which guarantee the best choice in any cases. Nevertheless the following advises will help the user to find appropriate settings. We recommend to always start a new measurement with the default parameters. The default parameters can be selected by a click in parameters menu on "Default parameters". The default parameters select the assisted mode. Then open the "Assisted mode parameters" panel from the menu bar (Parameter -> Assisted mode parameters). In this panel:

- select the emitting frequency that corresponds to the ultrasonic probe connected to it. The velocimeter can emit a very short ultrasonic pulse. This means that at high ultrasonic frequency, it is some time not possible to exactly select the frequency for which the probe is designed. This is not an issue as the bandwidth of the probe (around 50%) allows to use a frequency around its nominal value. - verify that the sound velocity corresponds to the liquid you are using. - select the starting depth by entering a value in the field named "From". - select a velocity scale much higher that the one you expect. This will insure that the measured profile will not contains aliased velocities. You will adapt after the velocity scale step by step - enter a temporary maximum depth in the field named "To", around few centimeters away from the starting depth. - select an acquisition time by moving the cursor on the sliding bar in order to have a blue or a yellow cursor.

Accept the settings and look at the resulting velocity profile. You will certainly have to improve the quality of the measured profile (see next chapter)

- You can then increase step by step the investigated depth until the whole range of interest is covered and only after adapt the velocity scale to let the velocity profile cover the widest range of the velocity scale as possible.

**Note:** By clicking on the velocity scale you can move the origin by dragging the mouse and leaving therefore more space for a positive or negative velocity.

---

<!-- source-pdf-page: 24 -->
## Source PDF page 24

### 4.3 Searching for artifacts

In many situations, interfaces and walls close to the measuring area generate artificial echoes which are named artifacts. These echoes appear on the screen as if they were real echoes. They are in fact images of real echoes (or duplicate echoes) that come after the PRF time. These artifacts disturb the measurement if they are strong and should be removed if possible. Unfortunately the only way to remove these artifacts consist to:

- move the probe away from the walls
- change the PRF value.

UDOP software let the user to easily change the PRF value in order to investigate its influence. The PRF can be changed in a floating panel, which is visible if the user has marked in the "option" panel the corresponding check box. Any changes in depth of an echo due to a change in the PRF value means that this echo is an artifact.

### 4.4 Adjusting the scales

Not all types of flows are bidirectional and even if they are, the range of positive and negative velocities can be different from each other. UDOP allows to move the origin of the velocity scale along the velocity axis in order to provide a part from its positive range to its negative range or vice-versa. This possibility allows to increase the maximum measurable velocity without changing other parameters and can be used whenever aliasing can disturb the measurement.

The modification of the velocity offset is realized by clicking on the velocity axis and moving the mouse up or down. A double click on the velocity axis cancel any applied offset.

If the selected measured data is an echo or an energy profile the scale can be changed by a mouse click on the arrows located beside the legend of the axis. Any change in the scale affects the recorded data.

The modification of the depth scale can also be realized the same way as the velocity scale. If the assisted mode is active, a change in the measured depth range may induce also a change the measurable velocity range.

**Note:** The two arrows, placed beside the legend, indicate that the scale can be changed.

---

<!-- source-pdf-page: 25 -->
## Source PDF page 25

### 4.5 Improvement of the quality of the measured profile

All the suggestions below refer to the assisted mode.

I see a profile with most of the values close to the zero line, but not zero.

Adapted the velocity scale to the measured data. If the maximum velocity scale is still lower then the maximum desired velocity, you must reduce the maximum depth.

I do not see any profiles or the profile contains a lot of zero.

If you have follow the recommendations mentioned in the previous chapters, the problem may comes from a really to much higher velocity scale or a lack of ultrasonic energy. Try to decrease step by step the velocity scale. If this does not improve the measurement, you should check the following points:

- are the coupling of the probe correct (no gas or bubble at the interface. - if crossing wall, verify that the angle between the probe axis and the surface of the wall is not to big (take care for a complete reflection). - verify that the echo profile is not saturated by visualizing this profile. After checking the above points you can do the following: - leave the assisted mode by unchecking the assisted mode enable field in the "Preference" menu. - Enter in the "Operating parameters" panel from the "Parameter" menu. - increase the sensitivity and see the result. If a "High" or "Very High" sensitivity value improves the result, the level of the received echoes are at the limit of the detection capability of the instrument. - Try to increase the emitting power

If none of these modifications improve the profile, you must add particles to the liquid in order to receive stronger echoes.

My profile looks like noise

This can be the case if the velocity scale is far to low, and the measured profile is a totally aliased profile. Increase step by step the velocity scale and looks on the result. If this does not improve the profile, you are certainly measuring in a noisy environment. Try to use a power line as far away as possible from any potential noisy source (switching power supply, heating system). Try to shield the probe cable with some metallic foils (alu foils used for food). If this last point improves the profile a special shielded probe can be used (available on request).

---

<!-- source-pdf-page: 26 -->
## Source PDF page 26

The beginning of the profile is not measured (zero values)

This may appears if the amplification level is to high and saturates the input stage. The TGC should be adapted. Please note that close to the transducer, the ringing effect of the piezo ceramic avoid any measurement. This is normal.

The end of the profile is not measured (zero values)

This may appear if the amplification level is to low or the liquid attenuates to much the ultrasonic waves. Try to improve the TGC, the level of the emission and the sensitivity.

### 4.6 Influences of interfaces

The interfaces reflect and modify the acoustic field. The intensity of the acoustic field received in a point depends on the material, on the shape and on the number of interfaces crossed by the ultrasonic waves. This means that it is often very difficult to have a good knowledge of the ultrasonic intensity. This lack of knowledge does not allow a precise determination of the size of the measuring volume. The interfaces may generate, in certain situations, artifacts and induce modifications in the velocity profiles as presented in the figures 1 and 2 below.

The ultrasonic beam BC reflected by the far interface of the figure 1 transforms this interface in a transmitter. The same particles contained in the liquid will backscatter a second time energy in the direction to the transducer. .

Figure 1

The depth associated to the path ABC is located outside the flowing liquid. Imaginary velocity components are added to the real velocity profile. The measurement of velocities near the far interface is affected by this phenomenon. The size of the ultrasonic beam

#### Figures and in-context visual analysis

**Reconstructed caption:** Probe, wall, beam path, and velocity profile.



**In context:** The beam crosses the vessel wall at A, samples the liquid toward B, and may receive a wall echo near C. The adjacent profile illustrates why probe placement and wall echoes affect the usable depth range.

---

<!-- source-pdf-page: 27 -->
## Source PDF page 27

determines mainly the level of this artifact. The effect mentioned above explains why it is impossible to obtain a zero velocity value at the far wall.

Figure 2

The figure 2 displays another situation some times encountered. The reflected ultrasonic waves inside a wall enlarge the ultrasonic beam and complicates the determination of the depth of the gates. This phenomena appears if the difference in the acoustic impedance between the liquid and the interface is high, as for instance in steel. In such a case, a lot of acoustic energy remains in the steel, which induces longer saturation of the receiver and a lost in depth resolution.

These reflections disturb the determination of the size and the shape of the measuring volume. The thickness, the acoustical impedance and the attenuation coefficient of the interface determine the level of this phenomenon.

### 4.7 Moving interfaces

Interfaces often give strong reflections. Despite of the many reflections which are necessary to reach the transducer, the energy reflected by these interfaces is often stronger than the energy coming from the particles flowing with the liquid. When some interfaces are in movement the correct estimation of all the velocity field is more difficult. The echoes generated by such interfaces may affect the velocity profile in some places due to the combination of many reflections. The Doppler frequency induced by these movable interfaces can not be removed if their values have the same values as the flowing particles.

### 4.8 Intensity of the ultrasonic field after crossing a wall

When an ultrasonic beam encounters a wall, a part of its energy is reflected and an other part is refracted. The intensity of both beams, the reflected and the refracted beams, can be computed when the two following parameters are known:

#### Figures and in-context visual analysis

**Reconstructed caption:** Multiple reflections inside a wall.



**In context:** Paths A, B, and C undergo different numbers of internal reflections. These delayed echoes can be mistaken for deeper targets and therefore appear as artifacts in a profile.

---

<!-- source-pdf-page: 28 -->
## Source PDF page 28

- the acoustic impedance of the medium; - the angle of incidence. The simple equations below assume a plane infinite wall or interface. This is of course never the case. Nevertheless, these three equations can really help because:

- they give an approximation of the total reflection angle;
- they predict the amount of ultrasonic energy that will penetrate in the liquid;
- they predict the amount of energy that tends to remain in the wall.

where: - R is the reflection coefficient, which is equal to the ratio of the reflected intensity to the incident intensity;

#### Equations reconstructed from the page image

*Transmitted intensity coefficient:*



$$
D=\frac{4Z_1Z_2\cos^2\alpha}{\left(Z_2\cos\alpha+Z_1\cos\gamma\right)^2}
$$

*Refraction angle:*



$$
\gamma=\arcsin\left(\frac{C_2\sin\alpha}{C_1}\right)
$$

*Reflected intensity coefficient:*



$$
R=\left[\frac{Z_2\cos\alpha-Z_1\cos\gamma}{Z_2\cos\alpha+Z_1\cos\gamma}\right]^2
$$

#### Figures and in-context visual analysis

**Reconstructed caption:** Reflection and refraction at an interface.



**In context:** The incident beam splits into reflected and transmitted components. Angles α, β, and γ and the two media's impedances/sound speeds feed the transmission and reflection coefficients reconstructed on this page.

---

<!-- source-pdf-page: 29 -->
## Source PDF page 29

#### Layout-preserving transcription

```text
     - D is the refraction coefficient, which is equal to the ratio of the refracted intensity
       to the incident intensity;
     - γ the refraction angle
     - Zi is the acoustic impedance of the medium i, which is equal to the product of
       the sound speed by the density of the medium i.


From these equations, it is possible to compute the value of the angle for which all the
ultrasonic waves will be reflected. By setting a value of 90 degrees to the refracted angle,
we can compute the value of the total reflection angle. For instance:


     - for aluminium, its value is 14 degrees;
     - for steel, its values is 15 degrees;
     - for plexiglas, its value is 33 degrees


We can also see the very strong influence of the wall material when the angle of
incidence is different from the perpendicular. The two examples below show this
influence very well:


                                             Table 1:
                          Material      α          γ      R       D

                          Plexiglas     30        66    0.42     0.58

                                        27        56     0.30    0.69

                                        25        50     0.26    0.74

                                        20        38     0.20    0.80

                                        15        18     0.15    0.85

                            Steel       14        69     0.95    0.047

                                        12        53     0.92    0.077

                                        10        42     0.90    0.094

                                        8         32    0.89     0.11

                                        4         15    0.88     0.12
```

---

<!-- source-pdf-page: 30 -->
## Source PDF page 30
