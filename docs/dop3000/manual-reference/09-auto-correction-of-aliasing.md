# 9. Auto correction of the aliasing

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 57-60.

---

<!-- source-pdf-page: 57 -->
## Source PDF page 57

## 9 Auto correction of the aliasing

The aliasing is inherent to the fact that the ultrasonic Doppler velocimetry uses a pulsed emission. This implies that the maximum measurable Doppler frequency is the half of the pulsed repetition frequency (Nyquist limit). Nevertheless, UDOP offers two ways to overcome that limitation. The first method is based on the assumption that the velocity can't change more than a define amount between two adjacent gates. This method implies that: - the measured velocity profile contains always at least one correct velocity value (not aliased) at a known depth. - The noise level must be much below the velocity deviation used to correct the profile. The second method uses two different pulsed repetition frequency and a special algorithm. This method allows to measure Doppler frequencies many times higher than the Nyquist limit and does not require any a priori knowledge. The basic idea of this method is to take into account the phase difference resulting from a change in the PRF between two successive emissions. By selecting the deviation between the two PRF, the user can define the maximum measurable velocity. More the PRF are close to each other, bigger will be the measuring range, but also bigger will be noise in the measurement. UDOP defines the difference between the two PRF in percent. To apply the auto correction of the aliasing, the following points must be respected: - the assisted mode must be disabled; - the velocity scale factor must equal to 1 To enable or disable the auto correction of the aliasing, simply click the button named "Aliasing auto correction is" which is found in the panel named "Filters". This click opens a panel in which you can select the auto correction method and their related parameters.

### 9.1 Auto correction using the jump method

This method is based on the assumption that the velocity can't change more than a define amount between two adjacent gates. Therefore, the user needs to enter: - The depth or the gate which will be used as the reference gate, the gate for which no aliasing ever appears. - The acceptable maximum deviation between 2 gates. This value is defined as a percentage of the maximum measurable velocity, which corresponds a Doppler frequency equal to PRF/2. - In order to be able to see corrected values, the velocity scale can be increased. The multiplication factor is entered in the parameter named "multiply display velocity scale".

---

<!-- source-pdf-page: 58 -->
## Source PDF page 58

When this method is enabled, each time a velocity profile is measured, UDOP will apply the following correction mechanism: - Initialize the correction factor to 0 - Starting from the reference gate, if the velocity difference between the present gate and the next following gate (at a higher depth) is above the defined limit, the correction factor is incremented or decremented of an amount corresponding to the uncorrected velocity scale. The correction factor is then added to the value of the following gate. - Repeat this mechanism for all the gates up to the last gate. - Repeat the same algorithm for the gates located at a depth lower than the reference gate. I order to see how the correction works, it is possible to see on the same graph the corrected and the uncorrected profiles. The 2 buttons "Show uncorrected profiles" and "Show corrected profiles" define how the profiles are displayed.

**Note:** If the auto correction of the aliasing is enabled, a calibrated velocity profiles in mm/s or mm*10 is added to the internal memory and therefore will be present in the binary data file.

### 9.2 Auto correction using the two PRF method

The two PRF method uses two different pulsed repetition frequency and a special algorithm in order to correct aliased values. This method always computes 2 velocity profiles. The first one is the same as the standard profile and uses the highest PRF. The second one is computed from the difference between the two PRF. As this second profile is much more noisy than the standard profile, it is used as a reference profile. Each value issue from the standard profiles is compared to the reference profiles. The computed deviation defines how many times the full scale velocity value, corresponding to the highest PRF, must be added or substracted to the value of the standard profile. The correction mechanism may be improved by applying a filter to the reference profile. This reduce its noise level and therefore improves the computation of the deviation. Two types of filter are available, the moving average and the median. In case of high level of corrections some peaks may still be present in the corrected profiles. The special designed "Jump filter" can then be applied to reduce considerably the presence of these peaks. I order to see how the correction works, it is possible to see on the same graph the uncorrected profiles, the reference profiles and the corrected profiles simultaneously. The 3 buttons "Show uncorrected profiles", "Show reference profiles" and "Show corrected profiles" define how the profiles are displayed.

---

<!-- source-pdf-page: 59 -->
## Source PDF page 59

**Note:** If this auto correction method is used and the echo profile is displayed, UDOP shows on the same graph the echo profile resulting from the 2 PRF (2 curves). As artifacts are very sensitive to the PRF value, this display insures that for both PRF values no artifacts are present in the profiles.

### 9.3 Structure of the recorded data for the two PRF method

When this auto correction method is enabled and the velocity profiles are displayed, the coded velocity values of the reference profile are always added just after the coded velocity values of the standard profile. Moreover, an additional velocity profile, calibrated in mm/s or mm/s*10 is added as a last profile. This calibrated profile is computed from the corrected velocity profile if it is visible, or from the reference profile if the corrected profile is not visible. In case of UDV 2D/3D the calibrated profiles are not present as the file already contains calibrated profiles. Nevertheless the coded values issue from the reference profiles are included. If the echo profiles are displayed the two echo profiles issue from each PRF are recorded, the first one corresponding to the highest PRF.

---

<!-- source-pdf-page: 60 -->
## Source PDF page 60
