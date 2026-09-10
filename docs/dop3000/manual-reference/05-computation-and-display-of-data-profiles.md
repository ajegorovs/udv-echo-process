# 5. Computation and display of data profiles

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 31-40.

---

<!-- source-pdf-page: 31 -->
## Source PDF page 31

## 5 Computation and display of data profiles

The velocimeter does not only computes and displays velocity profiles. It also allows to collect much more information in real time. These additional information are:

-the profile of the echo modulus -the velocity profile and the profile of the echo modulus

and with the "additional compute" software package;

-the profile of the Doppler energy -the profile and the corresponding histogram -the power spectrum of a selected gate -the velocity profile and the profile of the Doppler energy -the velocity profile and velocity versus time of many selected gates -the velocity profile and its evolution versus time -the velocity profile and the evolutionof the flow rate

### 5.1 Velocity profile

The velocity profile is the main display. The velocity profile is the result of the computation of Doppler frequency shifts coming from many gates placed along the ultrasonic beam. The DOP3000 displays the velocity values along its Y axis or the vertical axis. The measured velocity component is always the projection of the real velocity vector along the ultrasonic beam axis. All velocities values are in mm/s. If the Doppler angle is used (value different from 0), the velocimeter assumes that the user knows the real direction of the velocity vector and UDOP gives the modulus of the velocity vector, assuming that the measured component (along the ultrasonic beam axis) is the projection of the real vector over the ultrasonic beam axis.

The depths are the distances measured along the ultrasonic beam axis from the surface of the transducer to the beginning of the measuring volume. All depths are given in millimeters. In order to allow more space to the positive or negative values, the origin of the velocity scale can be moved by clicking the left mouse button when it the mouse is over the velocity scale and moving it (drag mode). A double click put the origin in the middle. This feature is only available if the software package "Additional compute mode" is installed.

---

<!-- source-pdf-page: 32 -->
## Source PDF page 32

### 5.2 Echo modulus profile

The echo modulus profile gives the evolution of the echo envelope of the ultrasonic signal received by the transducer. This display informs the user on the presence of high reflective structures and on a possible saturation of the receiver stage of the velocimeter.

As the saturation of the receiver stage is a key point for reliable measurements, this display is highly recommended for each new measurement. The echo modulus profile is the only display that allows the user to verify that a correct emission level and TGC amplification are selected.

The DOP3000 displays the echo modulus values along its Y axis or vertical axis. The numbers displayed on that axis do not have any unit. They are relative numbers and covers a range from 1 to 2048. As the available data are given in a byte format, a zoom capability is given by changing the scale of the Y axis. This is realized by clicking on the arrow above and below the Y axis legend.

### 5.3 Doppler energy profile

The displayed Doppler energy signal is the high-pass filtered echo signal. Only the echo modulus envelope of moving structures will be displayed. This signal enables the detection and visualization of high reflective moving structures.

The DOP3000 displays the Doppler energy values along its Y axis or vertical axis. The numbers displayed on that axis do not have any unit. They are relative numbers and covers a range from 1 to 2048. As the available data are given in a byte format, a zoom capability is given by changing the scale of the Y axis. This is realized by clicking on the arrow above and below the Y axis legend.

### 5.4 Histogram

The histogram of the velocity profile, the echo profile or the energy profile can be computed and displayed in real time.

This histogram displays its information in a color coded mode. The whole measured Y scale is divided in a user's defined number of classes. After the computation of a profile, for each gate that makes the profile, a class number is computed from the value found in the gate (velocity, echo, energy) and the corresponding class is then incremented . The value of each class is then converted to a color in a linear way. A zero value gives the background color and the color of the curve is attached to the maximum value found in all the classes. All the classes are then displayed.

---

<!-- source-pdf-page: 33 -->
## Source PDF page 33

### 5.5 Velocity versus time of a gate

This display shows the velocity profile and the evolution the velocity versus time of up to four gates. The position of the gates is selected on the graph that shows the velocity profile by placing a cursor on the data profile. The time scale of the graph that shows the velocity versus time can be changed in the windows named "V(t) parameters".

Adding a cursor on the graph that displays the velocity profile adds a line in the graph that displays the evolution of the velocity versus time.

**Note:** To move a cursor it is not necessary to place the mouse over the cursor. A click inside the graph will place the cursor at the mouse depth.

This measurement is only available if the software package "Additional compute mode" is installed.

### 5.6 Power spectrum of a selected gate

In pulsed ultrasound Doppler velocimetry the sampling volume contains not a unique particle but a lot of small particles having most of the time different shapes, different sizes and different acoustic impedances. As all of these particles contribute to generate a unique value of the amplitude of the echo for each emission, the evolution of the echo amplitude will fluctuate. The reason comes from the fact that some particles enter in the sampling volume and others leave it. This fluctuation in amplitude will remain after the demodulation process and will be present on the demodulated Doppler signal, often called I and Q signals. The level of this fluctuation is greatly influence by the shape of the ultrasonic beam, which defines the geometry and sizes of the sampling volumes. Moreover, all the Doppler frequency shifts induced by the movement of the particles are combined together. As all the particles do not have exactly the same velocity (in amplitude and in direction), and the Doppler angle changes during their journey across the sampling volume, the demodulated signals contain many Doppler frequencies.

The resulting demodulated signals I and Q contain therefore the combination of these phenomena. In order to have an idea of the aspect of a real demodulated Doppler signal issue from one gate, the figure below illustrates its evolution.

#### Figures and in-context visual analysis

**Reconstructed caption:** Example Doppler echo waveform.



**In context:** The irregular oscillatory signal is the raw information from which Doppler frequency is estimated; its changing amplitude anticipates the need for statistical and spectral displays.

---

<!-- source-pdf-page: 34 -->
## Source PDF page 34

The best way to analyze the frequency content of the demodulated echo signal issued from one gate is to compute its power spectrum. The power spectrum gives information on the distribution of the Doppler frequencies and their relative influences on the computed mean Doppler frequency, which is computed when the velocimeter displays the velocity profile.

Why using the power spectrum of one gate

When once looks at the velocity profile, each gate give a single value of velocity. These values are the result of a computation of the mean Doppler frequency, which is the mean value of the power spectrum. This means that no information is given about the distribution of the Doppler energy. The same value of velocity can result from many different frequency distributions. The display of the complete power spectrum is a good method to increase the knowledge on the measured velocity values.

How to use the information contained in the power spectrum

The following examples will display different situations where the power spectrum can increase the knowledge in the measured velocity values.

The example A in the figure above shows the computed power spectrum from a gate placed in the middle of a tube where a liquid is flowing. As shown in the power spectrum the sampling volume does not contain a single Doppler frequency. The width of the peak is related to the number of Doppler frequencies present in the sampling volume.

In situation B, the sampling volume has been moved closer to the wall of the tube. The width of the Doppler peak is now much larger which means that much more different velocities are present in the sampling volume. The power spectrum reveals also a small influence of the movements of the walls. As the power spectrum is computed from the high-passed filtered data, the amplitude of the power spectrum at the origin is always zero.

#### Figures and in-context visual analysis

**Reconstructed caption:** Histograms at two pipe locations.



**In context:** Moving the sample volume from A to B changes the velocity distribution. The histograms show that a gate near a different portion of the flow can have a different dominant velocity and spread.

---

<!-- source-pdf-page: 35 -->
## Source PDF page 35

The example C considers a rotating cylinder filled of liquid. The ultrasonic beam crosses the cylinder perpendicularly to the axis of the cylinder. The sampling volume is placed inside the cylinder in a position near the wall.

The power spectrum reveals a very strong influence of the movements of the walls of the cylinder despite the sampling volume does not touch a wall. This situation may appear if some of the multiple ultrasonic reflections may coincide with the sampling time of the echo. In such a case the velocity value is corrupted by the Doppler effect induced by the movement of the walls. The display of the power spectrum indicates clearly that the mean Doppler frequency computed is in fact the result of the mean value of two different velocity components, one coming from the movements of the walls and the other coming from the movements of the particles contained in the liquid.

C

How to visualize use the power spectrum

The DOP3000 can compute this power spectrum by means of an FFT algorithm. The data series is formed by samples taken on the demodulated I and Q signals for a selected depth which corresponds to the gate position. Before the computation of the power spectrum, the data series is filtered by a high pass filter which removes all the stationary components contained in the demodulated signals.

The display of the power spectrum of a gate is available in the compute menu. After its selection a panel named "FFT parameters" appears and enables the selection of the number of emissions used to compute the power spectrum. A hamming window can also be applied if desired. The cursor available in the velocity profile graph enables to define the position of the gate.

UDOP records both, the velocity profile and the power spectrum. Therefore both data will be available for further analysis. In order to make the reading of the frequency scale more easy the frequency scale is converted in velocity by using the standard Doppler formula. The FFT velocity (or frequency) resolution can be improved by using the velocity scale factor, available in the manual parameters menu. The available velocity scale factor are 1, 0.5 and 0.25.

#### Figures and in-context visual analysis

**Reconstructed caption:** Multi-peaked velocity histogram.



**In context:** Several peaks reveal more than one strong velocity population within the selected sample volume, so a single mean velocity can hide relevant flow structure.

**Reconstructed caption:** Selected sample position in a cylindrical flow.



**In context:** The marker shows that gate-specific displays refer to a small measurement region along the beam, not to the entire pipe cross-section.

---

<!-- source-pdf-page: 36 -->
## Source PDF page 36

The ordinate gives the amplitude of the power spectrum in dBm. This amplitude is the amplitude find at the BNC input. A mouse click on the arrow located above and below the legend of the vertical axis can adapt the level of the scale.

**Note:** The measurement of the power spectrum of a single gate is only available if the software package "Additional compute mode" is installed.

### 5.7 The velocity profile and its evolution versus time

This display shows the velocity profile and its evolution versus time by showing in a color coded fashion the velocity values in an additional graph. The time scale is defined by the acquisition time of a profile and the dimension of the graph. It can not be adapted.

**Note:** The measurement of the velocity profile and its evolution versus time is only available if the software package "Additional compute mode" is installed.

### 5.8 Raw data acquisition

UDOP allows to acquire raw data. The acquired raw data are the demodulated I and Q signals, after amplification. They are also filtered by the spatial filter. UDOP can acquire up to 15'000 couples of I, Q signals. Each value is recorded as a 16 bits signed integer.

After the trigger of the raw data acquisition process, UDOP records a user defined number of gates for each of the following emission until it reaches the user selected number of emissions. The position or depth of the first gate is defined by means of a cursor placed inside the velocity profile. The following gates, if any, are placed as defined by the resolution parameter.

At the end of the acquisition process, the user can repeat the acquisition and therefore adding to the current acquired block of data a new block, or can store the acquired data to a file.

To access this acquisition mode, click on the button named "acquire raw data" located in the "Tools" panel available in the menu bar.

**Note:** The acquisition of raw data is only available when the following conditions are met: - the assisted mode is disabled - both the software packages "Extended number of gates" and "extended resolution" are installed.

---

<!-- source-pdf-page: 37 -->
## Source PDF page 37

### 5.9 Flow rate versus time

The velocimeter can compute and display in real time the flow rate by integrating the velocity profile on a user's defined area.

The flow rate is computed by spatially integrating the velocity profile. The integration is carried out by summing the flow rates through several small regions (indicated by the shaded region in the figure below), each of them corresponding to one measured channel. The velocity is assumed to be uniform throughout each region. The cross- section of the conduit is always assumed to be circular, with a diameter equal to the spacing between the anterior and posterior wall indicators.

The formula below indicates how the flow rate is computed. "e" is the thickness of the semi-annular region and "v" the velocity component perpendicular to the cross section. These two relationships do not explicitly contain the diameter. The diameter is only used to determine the number of channels contained in the conduit.

For an even number of channels the flow rate is given by:

A precise evaluation of the flow rate is possible only if the axes of the pipe and of the ultrasonic field lie in the same plane, and if the flow field is axially symmetric. The size of the ultrasonic beam must also be much smaller than the diameter of the pipe.

#### Equations reconstructed from the page image

*Flow rate for an even number of channels:*



$$
Q=\frac{\pi e^2\sin^2\theta}{2}\left[V_{N/2}+V_{N/2+1}+\sum_{i=1}^{N/2-1}(V_i+V_{N-i+1})(N-2i+1)\right]
$$

*Flow rate for an odd number of channels:*



$$
Q=\frac{\pi e^2\sin^2\theta}{2}\left[\frac{1}{2}V_{(N+1)/2}+\sum_{i=1}^{(N-1)/2}(V_i+V_{N-i+1})(N-2i+1)\right]
$$

#### Figures and in-context visual analysis

**Reconstructed caption:** Annular integration model for flow rate.



**In context:** The pipe section is divided into concentric/semi-annular regions associated with measured channels. The even/odd summations on the page approximate the area integral by weighting paired velocities.

---

<!-- source-pdf-page: 38 -->
## Source PDF page 38

Knowledge of the Doppler angle θ is necessary for the computation of the flow rate. The flow rate is based on the computation of velocities in the flow axis. It is therefore necessary to compute these velocities from the only velocity component measured by the velocimeter which is the velocity in the direction of the ultrasonic beam. The graph below illustrates the error introduced in the flow rate computation as a function of the Doppler angle, for a few errors in the input value of the Doppler angle.

Error on the flow rate% Error on the Doppler angle 0 3 40

30 2 0

20 0

10                                                              1

```text
                                                                                       Doppler angle
                        0
                                 0                0        0             0                 0
                            40               50       60            70                80
```

The wall indicators

The diameter of the conduit is defined in an interactive manner, by placing on the velocity profile two indicators, one defining the position of the anterior wall, the other the position of the posterior wall. These indicators are represented by two cursors. These cursors are enabled when the flow rate computation mode is selected. The user should define the section used for the computation of the flow rate by placing the two cursors on the corresponding walls. The gate located at the position of the wall indicator belongs to the flow rate section. The left mouse button is used to place the first cursor and the right button mouse places the second cursor.

**Note:** The measurement of the flow rate versus time is only available if the software package "Additional compute Mode" is installed.

### 5.10 Raw data acquisition

UDOP allows to acquire raw data. The acquired raw data are the demodulated I and Q signals, after amplification. They are also filtered by the spatial filter. UDOP can acquire up to 15'000 couples of I, Q signals. Each value is recorded as a 16 bits signed integer.

After the trigger of the raw data acquisition process, UDOP records a user defined number of gates for each of the following emission until it reaches the user selected number of emissions. The position or depth

---

<!-- source-pdf-page: 39 -->
## Source PDF page 39

of the first gate is defined by means of a cursor placed inside the velocity profile. The following gates, if any, are placed as defined by the resolution parameter.

At the end of the acquisition process, the user can repeat the acquisition and therefore adding to the current acquired block of data a new block, or can store the acquired data to a file.

To access this acquisition mode, click on the button named "acquire raw data" located in the "Tools" panel available in the menu bar.

**Note:** The acquisition of raw data is only available when the following conditions are met: - the assisted mode is disabled - both the software packages "Extended number of gates" and "extended resolution" are installed.

---

<!-- source-pdf-page: 40 -->
## Source PDF page 40
