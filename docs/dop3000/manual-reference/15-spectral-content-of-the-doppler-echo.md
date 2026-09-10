# 15. Spectral content of the Doppler echo

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 103-104.

---

<!-- source-pdf-page: 103 -->
## Source PDF page 103

## 15 Spectral content of the Doppler echo

The sample volume in which the velocity is measured is of a finite dimension. Each particle which traverses the ultrasonic beam backscatter the acoustic waves for a short time. The duration of the backscattering time depends on the angle of incidence as well as on the particle velocity, and is referred to as the transit time. If the fluid contains small particles possessing different acoustic properties than the fluid, the echo signal amplitude will evolve over time depending on the passage of a group of particles through the sample volume. This results in a modulation of the echo signal which serves to broaden its frequency spectrum. The signal is further modulated by the non- homogeneity of the fluid-particle medium. This spectral broadening depends on the velocity at which the particles traverse the ultrasonic beam. The higher the velocity, the faster the signal will be modulated and its spectrum broadened. Since the Doppler signal is related to the velocity, it is possible to evaluate the effect of the transit time as a function of the Doppler frequency. One of several researchers who studied this effect was Newhouse [2], who estimated the spectral broadening δfd as:

where k is a constant between 2 and 3, depending on the ratio of the intensity of the acoustic wave at its center to its intensity near the periphery, λ is the wavelength and D is the diameter of the ultrasonic beam. For example, with an emission frequency of 3 MHz (λ = 0.5 mm), a transducer diameter of 10 mm and a Doppler angle of 45 degrees, the spectral broadening is on the order of 10%.

The spectral broadening created by the modulation of the echo signal amplitude may also be explained based on geometric considerations. The finite dimension of the sample volume implies that each particle contained within it is viewed from a slightly different Doppler angle. This results in a spread of Doppler frequencies corresponding to this small angle change.

As the ultrasonic waves propagate, they encounter different structures which may create echoes stronger than the echoes from the particles within the fluid. Furthermore, these structures may themselves be moving. Therefore, the echo signal may contain a certain number of stationary and quasi-stationary echoes of low frequency and large amplitude, as well as the echoes from the particles within the fluid at higher frequencies but of smaller amplitudes. The difference between the amplitudes of these two types of signals may be 20 to 60 dB. For the case of moving flow boundaries, the velocity of the wall creates a Doppler effect which must be filtered out. These low frequency components may be eliminated by the wall motion filter. Unfortunately, this hi-pass filter also

#### Equations reconstructed from the page image

*Transit-time spectral broadening:*



$$
\frac{\delta f_d}{f_d}=\frac{k\lambda}{D}\tan\theta
$$

---

<!-- source-pdf-page: 104 -->
## Source PDF page 104

diminishes the amplitudes of the already weak Doppler signals coming from the particles within the fluid.
