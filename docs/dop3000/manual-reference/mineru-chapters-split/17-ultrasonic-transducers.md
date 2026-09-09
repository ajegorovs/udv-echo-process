---
title: Chapter 17: Ultrasonic transducers
manual: DOP3000 Users Manual v6.6.1
pages: 107-108
chapter: 17
extraction_method: mineru
---

# Chapter 17: Ultrasonic transducers

Ultrasonic transducers

17 Ultrasonic transducers

The material most often used in the construction of ultrasonic transducers is a piezoelectric ceramic. Another material which may be used is the polymer polyvinylidene fluoride (PVDF) which possesses good piezoelectric properties, and has the additional advantages of being more flexible and having a smaller acoustic impedance than ceramic materials. PVDF is, on the other hand, less efficient. With the advent of composite materials [6], ultrasonic transducers have been produced which are as efficient as ceramic materials and which have a small acoustic impedance. They offer the advantage of a better acoustic coupling between the transducer and the medium, as well as the ability to produce a shorter ultrasonic impulse, due to their relatively high coefficient of absorption. A typical design is illustrated below.

The electrodes are positioned so that the ceramic operates in a piston-like mode.

The transfer of energy from the ceramic (medium 1) to the surroundings (medium 3) is determined by the characteristic impedances or acoustic impedance z of the two media, defined as:

\[
z = \rho c
\]

where \(\rho\) is the density of the medium and \(c\) is the speed of sound.

By placing an additional layer between these two media, the energy transfer may be optimized. The acoustic impedance of this middle layer should be:

\[
z _ {2} = \sqrt {z _ {1} z _ {3}}
\]

and its thickness:

\[
e _ {2} = (2 n - 1) \frac {\lambda_ {2}}{4}
\]

where \( n \) is an integer and \( \lambda_2 \) is the wavelength in the middle layer. This additional layer, called the quarter-wave layer, is used in the construction of most ultrasonic transducers.

The rear part of the transducer (called the absorber or backing) behaves like a shock absorber whose efficiency depends on its acoustic properties. The choice of the material

Signal Processing S.A. - DOP3000/3010 user's manual

17 - 1

Ultrasonic transducers

for the backing determines the type of acoustic impulses which may be emitted by the transducer. For a highly absorbent material, most of the energy is absorbed, tending to produce a short emission. For a weakly absorbing material, the energy at the rear of the transducer is returned to the front face, thereby increasing the energy transmitted out into the medium.

The electric energy transferred from the generator to the probe depends on their respective electric impedances. Adapting the electric impedance of the transducer to that of the generator using passive elements can optimize the transfer of energy. The reactive component  \( (x_{s}) \)  of the probe impedance  \( (z_{s} = r_{s} + jx_{s}) \)  may be eliminated with an inductance of  \( L = x_{s}/\omega \) . An impedance transformer assures the compatibility of the generator impedance with the corrected probe impedance.

17 - 2

Signal Processing S.A. - DOP3000/3010 user's manual