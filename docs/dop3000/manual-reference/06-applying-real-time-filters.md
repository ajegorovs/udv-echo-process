# 6. Applying real time filters

> Source: *DOP3000-3010 User's Manual*, software 6.6, revision 1. Source PDF pages 41-42.

---

<!-- source-pdf-page: 41 -->
## Source PDF page 41

## 6 Applying real time filters

The display of data profiles can be improved by the use of real time filters. These filters reduce the noise level and the variance of the measured profiles. Two types of filters can be applied for all the computed data profiles: - a moving average filter - a median filter The use of any of these filters do not affect the data value contained in the internal memory of the velocimeter. They will only modify the displayed data profiles. This allows the user to post process the data profiles in replay mode afterwards or with other user's software. The median filter is recommended when the data profiles contain random spikes particularly when the velocimeter is operated with a sensitivity parameter value equal to "high" or "Very high". The application of this filter greatly improves the display of the data profiles.

**Note:** The filters are only available when the software package "Advanced compute" is installed

### 6.1 The moving average filter

The moving average filter computes the arithmetic mean value for all the displayed gates based on a define number of profiles. The mean values of each gate are computed independently, which means that values of one gate does not affect the computation of other gates. Each time a new data profile is acquired, a new filtered data profile is computed using the N last measured profiles, where N is a user's defined number. When the moving average filter is applied to data profiles containing low Doppler energy the zero values that may some times appear can be optionally rejected from the computation. This option is enabled if the check box named "Reject zero" is marked. This option allows to compute an unbiased mean data profile.

To apply the moving average filter:

Select the menu named "Filters" and click on the named of the filter to apply. The button named "Define" allows to fixe the filtering parameters.

The use of the moving average filter can mask any aliasing that may be present ! on velocity values. For this reason, only apply this filter if you are sure that the profiles do not contain any aliased values.

---

<!-- source-pdf-page: 42 -->
## Source PDF page 42

### 6.2 The median filter

Median filters reject erroneous values by ordering a set of values by increasing order and output as a filtered value the value located in the middle of the ordered table. The main advantage of this filter is its aptitude to reject values far from the mean value like random spikes. The median filter is recommended when the data profiles contain random spikes particularly when the velocimeter is operated with a sensitivity parameter value equal to "high" or "Very high". The application of this filter greatly improves the display of the data profiles.
