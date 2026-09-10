# 13. UDV Simulation software

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 93-98.

---

<!-- source-pdf-page: 93 -->
## Source PDF page 93

## 13 UDV Simulation software

A simulation software is available to help the selection of the geometry, the type of transducers and the operating parameters for UDV-2D and UDV-3D measurement. This software also allows to simulate the 1D behaviour. It simulates flows, which are characterized by defined velocities along each axis (Z in 1D, Y,Z in 2D and X,Y,Z in 3D). It shows the influence of the parameters such as the angle of the receivers. We really recommend you to use it. To execute the simulation software select the menu "UDV Mode" and then click the button named "UDV simulation" In simulation, the display is divided into two main areas; the frist one displays the result and the second one shows the control area. Before doing any simulation you must define the operating condition and the way the transducers are arranged.

### 13.1 UDV 1D simulation

where t is the sampling time, c the sound velocity and Prf the pulsed repetition frequency. In order to keep a good spatial resolution, the first echo (i=0) must strongly dominate. This is true if - the liquid attenuates the ultrasonic waves - the PRF is low - the particle is far away The 1D simulation allows to investigate how the above parameters influence the measured data profile. If the maximum measured depth, the one corresponding to the selected PRF value, is lower than the simulation depth, the simulation software will take into account the particles located deaper than the maximum depth and therefore will allow to investigate how the previous echoes influence the current one.

#### Equations reconstructed from the page image

*Depth contributions from periodic emissions:*



$$
P=\sum_{i=0}^{N}\frac{c\,[t+i\,\mathrm{Prf}]}{2}
$$

---

<!-- source-pdf-page: 94 -->
## Source PDF page 94

### 13.2 Define probes and geometry in UDV 2D/3D

A click on the button named "Define probes and geometry" opens a panel, which enables the user to define the type of transducers and the way they are arranged.

B

C1                         C2

A

The frequency of all the transducers must be the same. The emitter should have the thinnest beam as possible. So try to use a piezo diameter as large as possible in order to reduce the divergence of the beam. The receivers should have a large beam so try to use a small piezo diameter. Often, a compromise should be taken in order to optimize the size of the sampling volumes and the depths over which measurements must be realized. The minimum size of the sampling volume always appears at the depth that corresponds to the crossing of all the ultrasonic beams axis. The following parameters must be defined:

Distance between emitter and receivers (A)

This distance is the distance in millimeters between the center of a receiver and the emitter when the receiver is not shifted (C1,2,3 value = 0). Receiver angle (B)

This angle is the angle in degrees between the US beam axis of a receiver and the US beam axis of the emitter. It must be the same for all recievers. The shifted distances (C1,C2 and C3)

The receivers are not necessarily placed in the same plane as the emitter. The entered distance is the distance from the center of the receiver to the crossing point of the ultrasonic beam axis of the receiver and the normal to the beam axis of the emitter passing at the origin (Z=0). A positive value indicates that the receiver is moving in direction to the crossing point of all the ultrasonic beams axis. Transducer used as the emitter

Select a transducer from the list. The choice of the this parameter sets the ultrasonic frequency, which must be the same as the one used for the receivers.

#### Figures and in-context visual analysis

**Reconstructed caption:** UDV-2D probe-geometry editor.



**In context:** The simulator encodes receiver angle, lateral offset, and depth relative to the emitter. These values determine where the beam axes intersect.

---

<!-- source-pdf-page: 95 -->
## Source PDF page 95

The "ideal" selects a transducer operating at the same frequency as the receivers, with no divergence and a very narrow beam (0.1 mm). Transducer used as the receivers

Select a transducer from the list. All receivers must use the same model of transducers.

When no simulation is runing, the simulation software displays the borders or the limits of the global sampling volumes over the measuring depth. These borders are displayed by 2 green lines. The 2 displayed red lines are the axis of the US beam of two receivers. As you can realize, the size of the global sampling volumes are much bigger in UDV 2D/ 3D mode than the normal sampling volume in UDV 1D mode. The choice of the ultrasonic probes and the way they are arranged have a very big influence on their sizes and their evolutions over the measuring range.

Global sampling volume

US beam axis

### 13.3 The simulation parameters

The simulation parameters are defined in a specific panel which is accessed by a click on the button named "simulation parameters". The panel contains an area in which you can select between the 2D or 3D mode. All other parameters are standard UDV parameters, excepted the 2 following specific parameters: Liquid attenuation This parameter defines in dB/cm the attenution of the ultrasonic waves when they propagate into the liquid. This parameter is mainly used in 1D mode to study the influence of the previous emission. Lowest echo level This parameter defines the minimum level of the echo issued from a particle in order to take into account that particle. A very sensitive simulation enlarged the sampling volumes. Particles density The simulation is based on movements of particles distributed uniformly in the investigated depth. If not enough particles are simulated, holes or zero values will appear in the result. If to many particles are used, the simulation will take a very long time. In most situations, a value between 1 and 10 are used in 2D mode and between 0.5 and 0.05 in 3D mode.

#### Figures and in-context visual analysis

**Reconstructed caption:** Sampling-volume size versus depth.



**In context:** The diverging curves show that intersection dimensions change with depth and probe arrangement. Spatial resolution is therefore position-dependent in a multi-probe measurement.

---

<!-- source-pdf-page: 96 -->
## Source PDF page 96

The total number of particles that will be used is displayed beside this parameters. Display scale factor This parameter defines the velocity or Doppler frequency scale. The maximum scale value is equal to the theoretical value plus the percentage defined by this parameter.

### 13.4 Range and velocity field

The simulation is done over a range defined by two depths, measured along the ultrasonic beam axis of the emitter. Two inputs field define the first and last analyzed depths. Between these two limits, flowing particles will be simulated. Two types of velocity field can be simulated in 1D and 2D and only one in 3D. In all modes the velocity field can be defined by a source of particles (a point), which emits particles in all directions. The module of the velocity vector is fixed for two specific directions (position 1 and 2) and vary linearly between these directions. The position of the source of particles defines the velocity field. In 1D or 2D mode the velocity field can also be generated by a rotation of all particles around a fixed point, the source.

### 13.5 Doing a simulation

Six types of results are available: Show flowing particles

This simulation shows where the particles are placed and how they moved. Moreover, you can see the locations of the partciles that are used to generate the echo from one couple emitter-receiver. These particles are displayed in green. You can clearly see that these particles are not distributed uniformly arround the emitter axis. This explains why: - the way the probes are arranged is important; - the sampling volumes are not the same for all receivers and therefore enlarge considerably the global sampling volume. (the global sampling volume is the volume that contains all the sampling volumes issued from all the receivers).

Show Doppler frequencies

This is maybe the most important simulation as the results issued from this simulation show how the parameters match the requirements. Two curves are displayed in each graph. The blue one shows the theoretical or reference curve (based on the input velocity field) and the red one the curve issued from the simulation. Any mismatch between these two curves tell that some parameters have to be changed or improved. Show the velocity profiles

---

<!-- source-pdf-page: 97 -->
## Source PDF page 97

The results issue from this simulation show how close are the results from the theoretical value. Show the velocity modulus and phase

The results issue from this simulation show an other type of profiles. Show the simulated IQ signal

The results issue from this simulation show the evolution of the I and Q signals Show the number of particles in gates

The results issue from this simulation show how many particles are contained in each gates. If this number is below around 10, the amount of generated particles must be increased via the "Particles density" parameter.

### 13.6 UDV 2D simulation: an example

The purpose of this chapter is to demonstrate the use of the simulation software. We would like to measure 2D velocity profiles in a liquid flowing in a channel. The interesting depths are assumed to be from 30 to 60 mm.

The expected velocity are: Vy = 200 mm/s Yz = 50 mm/s

Let's start UDOP and select the channel 10, as UDV 2D/3D mode uses the parameters from the channel 10. As for all new measurements, select the factory settings. Then click on the button named "UDV simulation" available in UDV Mode menu. The simulation software then starts. Let's open the probe selection panel by a click on "Define probe and geometry" and select the following values: - for the emitter "TR0408LS" - for the receivers "TR0405LS" - "20" for the distance between the emitter and the receivers - "20" for the angle between the emitter and the receivers - "0" for the shifted distance of the receivers

After "Accept" you will see then on the screen a display that shows in red, the US beam axis of the transducers and in green, the evolution of the borders of the global sampling volumes. You can notice that the measurement depth does not fit our requirement. So let's define the measuring range. Click on the button named "Velocity and depth" and enter the following values: - 60 mm in the button named "To mm"

---

<!-- source-pdf-page: 98 -->
## Source PDF page 98

- 30 mm in the button named "From mm"

The needed velocity range is defined by the position of the source of particles and by the value entered for the two specific positions of the direction vector. In our case, let's enter: - 200 mm/s for the velocity vector in position 1 and 2 - 30 mm for Z position of the source - 100 mm for Y position of the source

```text
  We are now ready to perform the first simulation. Click:
             -   "Accept"
             -    "Run simulation"
```

During the simulation the software computes and displays, in red the computed Doppler frequencies, and in green the theoretical values or the expected values. The US beams cross at a depth which is a little bit to far away from the starting depth. The size of the sampling volumes can be reduced if the distance between the receivers is reduced. Click: - "Stop"; - "Define probes and geometry"; - Enter "15" for the distance between the emitter and the receivers; - "Accept".

As you can realize, the US beams cross now at around the middle of the depth range and the size of the sampling volumes are more or less constant. Let's do the simulation, and click "Run simulation". All the Doppler frequencies are measured correctly. Let's have a look on the velocity profiles. Click: - "Show velocity profiles"

They are also measured correctly and the variance of the measurement is correct. The way we setup the transducers are now correct and the selected parameters fit our requirement. These parameters can be used by UDOP after exiting the simulation software, and if desired, the real UDV 2D mode can be executed. One thing the simulation can't do, is the definition of the TGC level. So, for all new settings, it is necessary to define a correct TGC level. This is realized by means of the display of the echo amplitude. Note that the TGC is the same for all the receivers and only the Uniform definition is available.
