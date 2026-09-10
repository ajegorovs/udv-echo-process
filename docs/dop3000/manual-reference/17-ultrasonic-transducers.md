# 17. Ultrasonic transducers

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 107-108.

---

<!-- source-pdf-page: 107 -->
## Source PDF page 107

## 17 Ultrasonic transducers

The material most often used in the construction of ultrasonic transducers is a piezoelectric ceramic. Another material which may be used is the polymer polyvinylidene fluoride (PVDF) which possesses good piezoelectric properties, and has the additional advantages of being more flexible and having a smaller acoustic impedance than ceramic materials. PVDF is, on the other hand, less efficient. With the advent of composite materials [6], ultrasonic transducers have been produced which are as efficient as ceramic materials and which have a small acoustic impedance. They offer the advantage of a better acoustic coupling between the transducer and the medium, as well as the ability to produce a shorter ultrasonic impulse, due to their relatively high coefficient of absorption. A typical design is illustrated below.

The electrodes are positioned so that the ceramic operates in a piston-like mode.

The transfer of energy from the ceramic (medium 1) to the surroundings (medium 3) is determined by the characteristic impedances or acoustic impedance z of the two media, defined as: z = ρc

where ρ is the density of the medium and c is the speed of sound. By placing an additional layer between these two media, the energy transfer may be optimized. The acoustic impedance of this middle layer should be:

z2 =      z1 z3

and its thickness:

where n is an integer and λ2 is the wavelength in the middle layer. This additional layer, called the quarter-wave layer, is used in the construction of most ultrasonic transducers.

The rear part of the transducer (called the absorber or backing) behaves like a shock absorber whose efficiency depends on its acoustic properties. The choice of the material

#### Equations reconstructed from the page image

*Acoustic impedance:*



$$
z=\rho c
$$

*Quarter-wave matching-layer impedance:*



$$
z_2=\sqrt{z_1z_3}
$$

*Quarter-wave matching-layer thickness:*



$$
e_2=(2n-1)\frac{\lambda_2}{4}
$$

#### Figures and in-context visual analysis

**Reconstructed caption:** Ultrasonic transducer cross-section.



**In context:** The ceramic generates/receives ultrasound, the quarter-wave layer improves acoustic matching, the backing damps ringing, and the steel case/coaxial cable provide mechanical and electrical integration.

---

<!-- source-pdf-page: 108 -->
## Source PDF page 108

for the backing determines the type of acoustic impulses which may be emitted by the transducer. For a highly absorbent material, most of the energy is absorbed, tending to produce a short emission. For a weakly absorbing material, the energy at the rear of the transducer is returned to the front face, thereby increasing the energy transmitted out into the medium.

The electric energy transferred from the generator to the probe depends on their respective electric impedances. Adapting the electric impedance of the transducer to that of the generator using passive elements can optimize the transfer of energy. The reactive component (xs) of the probe impedance (zs = rs + jxs) may be eliminated with an inductance of L = xs/ω. An impedance transformer assures the compatibility of the generator impedance with the corrected probe impedance.

rs              L=Xs/ω

generator transducer

#### Equations reconstructed from the page image

*Equivalent transducer impedance and tuning inductance:*



$$
z_s=r_s+jx_s,\qquad L=\frac{x_s}{\omega}
$$
