# 12. 2D / 3D Ultrasonic Doppler Velocimetry

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 85-92.

---

<!-- source-pdf-page: 85 -->
## Source PDF page 85

## 12 2D / 3D Ultrasonic Doppler Velocimetry

2D or 3D Ultrasonic Doppler Velocimetry measuring technique is a method that enables the measurement of two velocity components (U and W) or three velocity components (U,V and W) simultaneously along a line. UDV-2D and UDV-3D have all the advantages of classical ultrasonic Doppler velocimetry, such as the capacity to realize measurements in non translucid liquids. One of the most interesting property of these techniques compared to other techniques that can measure simultaneously more than one velocity component is its real time feature. Only few tens of milliseconds are necessary to compute and display a complete set of 2D or 3D velocity profile.

### 12.1 UDV-2D/3D measurement principle

UDV-2D is based on a 3 transducers system, whether UDV-3D is based on a 4 transducers system. Only one transducer is used as an emitter. The two or three others are used as receivers. For UDV-2D measurements the three transducers are arranged as displayed in figure 1. The two receivers are placed on each side of the emitter and at the same distance from it. All ultrasonic beam axis cross at the same point and are contained in the same plane. The piezo surface of these three transducers are not necessarily alined along the X-axis. This arrangement allows to measure velocities along the ultrasonic beam of the emitter in many points. The depths over which measurements are available depend on the geometry of the ultrasonic beam of the transducers, on their distance between each other and on the receiver angle (the angle between the emitter's beam and one of the receiver's beam).

Figure 1

#### Figures and in-context visual analysis

**Reconstructed caption:** UDV-2D probe geometry.



**In context:** One emitter and two receivers measure projections in a common plane. Their known axes allow the in-plane velocity components u and w to be reconstructed.

---

<!-- source-pdf-page: 86 -->
## Source PDF page 86

For UDV-3D measurements, the same kind of arrangement is used, as one can see in figure 2. A central transducer is used to emit ultrasonic bursts and three lateral transducers, placed uniformly (120 degrees) around the emitting transducer, are used to receive the echoes. Again, the piezo surface of these four transducers are not necessarily within the same XY-plane.

Figure 2 UDV-2D/3D coordinate system

Each set of emitter-receiver gives one Doppler frequency profile. These profiles are processed by the software of the instrument in order to give the velocity components in the following cartesian coordinates system: For 2D - The origin of the coordinate system is placed on the center of the emitter's piezo surface. - The Z axis coincides with the axis of the emitting transducer, and is pointing away from it. - The X axis is perpendicular to the Z axis and is pointing from the emitter towards receiver 1.

For 3D: - The origin of the coordinate system is placed on the center of the emitter's piezo surface. - The Z axis coincides with the axis of the emitting transducer, and is pointing away from it.

#### Figures and in-context visual analysis

**Reconstructed caption:** UDV-3D probe geometry.



**In context:** Adding a third receiver provides three independent projections, enabling reconstruction of u, v, and w when the beam geometry is calibrated.

---

<!-- source-pdf-page: 87 -->
## Source PDF page 87

- TheY axis is perpendicular to the Z axis and is pointing from the emitter towards receiver 2, crossing its US beam axis. - The X axis is such as (x,y,z) is a direct orthonormal coordinate system

### 12.2 UDV 2D/3D spatial resolution

In UDV 2D/3D the definition of the lateral dimensions of the sampling volume is not as simple as in 1D. This results mainly from the fact that each couple emitter-receiver is not the same. Emitting on one transducer and getting the echoes from an other one means that the radial location of the centers of the sampling volumes change over the measuring depth, as represented in the figure below.

receiver

emitter

As UDV 2D/3D uses 2 or 3 couples emitters-receivers, for a defined depth, more than one sampling volumes will be involved. Therefore, correct measurements will be available only if the flow field in each sampling volume is identical. In such a case, the sampling volumes corresponding to a particular depth, can be combined in a unique one, called global sampling volume, which has a much bigger dimension than in ID.

### 12.3 UDV-2D/3D probes

The UDV-2D/3D mode uses standard probes. Their choice and the way they are arranged (distance to the emitter, receiver angle) depends on the measuring range, the depth to be analyzed and the velocity range. For quantitative measurements it is necessary to take into account the shape of the ultrasonic beam generated by each transducer. UDOP software takes into account the ultrasonic beam properties, by asking the user to specify the type of transducers he uses as emitter and receiver. A careful analysis shows that a narrow beam is needed for the emitter and a wider beam for the two receivers. Geometrical parameters also have to be entered, such as the distance between the emitter and a receiver, the shifted distance and the angle between the ultrasonic beam generated by the emitter and the one generated by any receiver. In order to optimally choose transducers and the geometry, it is greatly recommended to use the simulation software which is included in UDOP.

#### Figures and in-context visual analysis

**Reconstructed caption:** Intersecting 2D/3D sampling volumes.



**In context:** The colored ellipses show where the emitted and received beams overlap. Only those intersections correspond to matched component measurements at a common spatial location.

---

<!-- source-pdf-page: 88 -->
## Source PDF page 88

### 12.4 Connecting the UDV 2D/3D probes

UDV-2D and UDV-3D probes are connected to special BNC, located in the front panel, as displayed in the figure below.

-   The DOP BNC connector named "EMI" must be connected to the emitting probe.

- The receiving probes must be connected to "REC1" and "REC2" for UDV 2D mode and "REC1", "REC2" and "REC3" for UDV 3D mode.

Please note that it is not necessary to turn off the power supply of the DOP when the probes are connected.

### 12.5 Measuring UDV 2D/3D profiles

The measurement of UDV 2D/3D profiles uses its own parameters. UDOP saves the current channel parameters before switching to UDV 2D or 3D mode.

**Note:** The assisted mode is not available in UDV 2D/3D mode. If the assisted is selected, UDOP opens a panel that will inform that the assisted mode will be disabled.

After selecting the UDV 2D or 3D mode, UDOP opens a panel in which it is possible to choose the probes and to define the way the probes are arranged. The operating ultrasonic frequency is defined by the emitting probe. On exit, if the apply button is clicked, UDOP uses the current parameters linked to the UDV 2D/3D mode and starts the measurement of the Doppler frequencies. As in UDV 1D mode the parameters can be changed and adapted using the normal mode. Nevertheless, a restriction applies: - The same TGC values are used for all the receivers and only the uniform mode is available.

We recommend to execute the following steps: - Select the position of the first gate;

#### Figures and in-context visual analysis

**Reconstructed caption:** Rear-panel connector assignment for UDV-2D/3D.



**In context:** The connector labels map emitting and receiving probes to the DOP3010 channels; correct cabling is essential because geometry and recorded component identity depend on this mapping.

---

<!-- source-pdf-page: 89 -->
## Source PDF page 89

- Select the number of gates, the resolution and the PRF in order to cover the desired depth; - Select a value of 1 for all the velocity scale factors; - Select the maximum TGC value; - Apply the changes.

You should first investigate the Doppler frequencies and the echo profiles. In order to be sure that there is no saturation on all receivers, you should have a look on the echo profile. The echo profile will also help you to see if some artefacts are present. For their detection we recommend to use the floating PRF panel (see preferences options). This panel allows a fast access to the modification of the PRF value step by step. A good PRF value is the one for which a small change in its value does not imply any changes in the echo profiles and in the Doppler frequency profiles. The auto correction of the aliasing is a tool that can extend the range of the measurable Doppler frequencies and velocities. Do not hesitate to use it. This tool will also inform you if the measured profiles are aliased or not. When stable profiles are measured you can then display the velocity components profiles or the modulus and angle profiles of the real velocity vectors. UDOP can display the measured velocities as vectors. The selection of this type of display is available in the "Display" tab in the main menu. A click on "Show vectors" select this display. A second click will return to the profiles mode. Note that "Show vectors" is only visible when UDOP measures velocities. The display of the vectors can be improved by moving the vertical position of the origin and of the end the depth scale (vertical axis). With the mouse go over the starting position or the end of the vertical axis (the mouse cursor will change) then click and drag vertically.

### 12.6 Type of data recorded in UDV-2D/3D

In case of UDV 2D/3D the following information are recorded for each measured profile in the binary data file: Compute mode: Doppler frequency - C1: Coded Doppler frequency profiles receiver 1 - C2: Coded Doppler frequency reference profiles receiver 1 - C3: Coded Doppler frequency profiles receiver 2 - C4: Coded Doppler frequency reference profiles receiver 2 - C5: Coded Doppler frequency profiles receiver 3

---

<!-- source-pdf-page: 90 -->
## Source PDF page 90

- C6: Coded Doppler frequency reference profiles receiver 3
- C7: Calibrated reference profile in Hz*10 of receiver 1
- C8: Calibrated reference profile in Hz*10 of receiver 2
- C9: Calibrated reference profile in Hz*10 of receiver 3

**Notes:** Curves C2,C4, C6, C7, C8 and C9 are only present if the auto correction of the aliasing is enabled and uses the two PRF method. Curves C5,C6, and C9 are only present in UDV 3D

Compute mode: Echo - C1:Echo profile receiver 1 - C2: Echo profile receiver 1, second PRF - C3:Echo profile receiver 2 - C4: Echo profile receiver 2, second PRF - C5:Echo profile receiver 3 - C6: Echo profile receiver 3, second PRF

**Notes:** Curves C2,C4 and C6 are only present if the auto correction of the aliasing is enabled and uses the two PRF method Curves C5 and C6 are only present in UDV 3D

Compute mode: Velocity Vx, Vy, Vz - C1: Coded Doppler frequency profiles receiver 1 - C2: Coded Doppler frequency reference profiles receiver 1 - C3: Coded Doppler frequency profiles receiver 2 - C4: Coded Doppler frequency reference profiles receiver 2 - C5: Coded Doppler frequency profiles receiver 3 - C6: Coded Doppler frequency reference profiles receiver 3 - C7: Calibrated velocity component Vx - C8: Calibrated velocity component Vy - C9: Calibrated velocity component Vz

---

<!-- source-pdf-page: 91 -->
## Source PDF page 91

**Notes:** Curves C2,C4 and C6 are only present if the auto correction of the aliasing is enabled and uses the two PRF method. Curves C5,C6, and C7 are only present in UDV 3D

Compute mode: Velocity modulus, phases - C1: Coded Doppler frequency profiles receiver 1 - C2: Coded Doppler frequency reference profiles receiver 1 - C3: Coded Doppler frequency profiles receiver 2 - C4: Coded Doppler frequency reference profiles receiver 2 - C5: Coded Doppler frequency profiles receiver 3 - C6: Coded Doppler frequency reference profiles receiver 3 - C7: Calibrated velocity modulus - C8: Calibrated velocity azimuthal angle in deg*10 - C9: Calibrated velocity elevation angle in deg*10

**Notes:** Curves C2,C4 and C6 are only present if the auto correction of the aliasing is enabled and uses the two PRF method. Curves C5,C6, and C8 are only present in UDV 3D

The recorded information on the ASCI file are similar, but no coded profiles are present.

### 12.7 Add user's specific ultrasonic probe

UDV 2D/3D needs to know the shape of the ultrasonic beam generated by the transducer. If the user wish to use non standard probes, he must add the probes to the list of available probes. The button named "Define probe" in the probe selection panel allows to add probes to the list. After a click on that button a new panel opens. To add the probe you must follow the following steps in the "UDV MD probe parameters" - click the "Add" button - enter the name of the added probe in the edit zone labled "Reference" - enter the parameters attached to the probe: - US frequency in kHz - diameter of the US beam measured at the probe surface - diameter of the US beam measured at the focal zone

---

<!-- source-pdf-page: 92 -->
## Source PDF page 92

- distance from the surface of the probe to the focal zone - divergence of the beam (half angle) - attenuation coefficient in dB/mm. Note that the attenuation coefficient is only used in simulation mode.

A click on the "Done" button close the panel. The new added probe appears then in the list of available probes.
