---
title: Chapter 10b: Data File Operations
manual: DOP3000 Users Manual v6.6.1
pages: 76-80
chapter: 10b
extraction_method: mineru
---

# Chapter 10b: Data File Operations

Storing and reading measures

\[
\text {Depth} [ m m ] = \operatorname{Par} [ 1 9 ] \cdot \left[ \frac {\operatorname{Par} [ 9 ] + (\operatorname{Par} [ 1 0 ] + 1) (i - 1)}{2 \cdot \operatorname{Par} [ 2 9 ]} - \frac {\operatorname{Par} [ 4 6 ]}{2 \cdot 1 0 ^ {6}} \right]
\]

where:

Par[x] is the binary value (format signed integer 4 bytes) located at offset x from the beginning of the binary parameters bloc.

i the gate number, starting from 1.

Note: The binary data file includes also a pseudo profile that contains the values of the depths of all the gates.

10.10 Reading a binary DOP3000 file

The DOP3000 can read and replay a measure from a binary DOP3000 file. The binary file format is the only file format that can be read by the UDOP software. Reading or replaying a measure allows the user to visualize slowly the measured profiles, to post process the data profiles and also to re-record the data with new processing conditions. This last point enables to change the file format, to compute statistical values and to save and keep only a portion of the measured data profiles.

When replayed, the data profiles can be visualized step by step, in a forward or backward direction, or continuously with the adjunction of a user's defined delay between each profile. In replay mode, the status window displays no more the time between acquired profiles but the time elapsed from the first profile of the file in milliseconds. All the menus that are used to define a parameter value that fixes the acquisition characteristic are disabled and only the value used during the acquisition of data profiles are shown.

Note: An easy way to visualize the parameters values used in a binary data file consists to recall the parameters from the file. (“parameters” -> “Recall parameters” -> “From file”)

10 - 16

Signal Processing S.A. - DOP3000/3010 user's manual

Storing and reading measures

To read a measure

Click on the text named “file” located in the menu bar then select “Get data file”. This opens the get file window:

If the preview button is checked, the content of the selected file can be visualized. It shows the first profile in the selected block. The “Preview” button is only available if the “Advanced recording feature” software package is installed.

A data file must be selected in order to see the button “Accept”. Any click on this button transfers the content of the data file into the memory, closes the “Get File” window and starts the display of the profiles.

The way the profiles are displayed is controlled by the following panel

This panel allows to visualize the profiles using two different methods.

The first one replays continuously the data profiles. The display rate is the same as during the measurement if the button named “Real time” is marked or at a user’s defined rate if the button named “User’s defined” is marked.

Signal Processing S.A. - DOP3000/3010 user's manual

10 - 17

Storing and reading measures

The second one replays the data profiles step by step. A sliding bar and four additional buttons allow to choose the profile.

More the cursor of the sliding bar is moved away from its middle position more fast is the update rate of the display.

If many blocks of data are available, it is possible to visualize only the profiles that belong to same block. This is the case if the button labeled “All block” is not marked. In such a case, the button labeled “Block” allows to select the block. The same procedure applies if the data file contains many channels.

To leave the replay mode click on the button labeled "Measure".

10.11 Updating data files

The “Advanced recording features” software package allows to convert many UDOP data files acquired by a previous software version to the current software version of UDOP. This allows to keep all data files up to date. The conversion takes place in a batch process. To execute this procedure, the following steps must be performed:

1. Place all the binary data files that must be converted in an empty directory of your choice.

2. Execute UDOP

3. Select the command located in the file menu "Update files".

This command opens a panel which allows to select the source directory (the one mentioned above) and the destination directory. If an ASCII data file must also be created during the conversion process, be sure that the respective ASCII requested line is checked (green mark).

3. Execute the command by a click on the button "Execute"

Note: This batch procedure takes only into account the binary data files (*.bdd). The file names remain unchanged. This means that if the source and destination directory are the same, the files will be overwritten.

It is highly recommended to keep a copy of the original data files.

10 - 18

Signal Processing S.A. - DOP3000/3010 user's manual

Storing and reading measures

Do not apply this batch procedure on data files acquired by a software version of UDOP that is newer than the one you used.

This Update procedure can also be used to convert WDOP data files, the one coming from a DOP2000.

10.12 Comparing recorded data profiles

UDOP allows to read a single or many profiles from different bdd data files and to display them in a single graph. This enables an easy way to see any differences between profiles.

To access this function execute the following procedure:

- Select Compare profiles in the File menu

- Select New comparison

- Select the file from which you would like to read profiles

- Once selected, fill the option panel:

The displayed profile will result from a computation of a mean profile computed from the two limits, Compute mean from and To for the profiles located in the blocks region defined by From block and To, for the specified channel Using channel, considering the curve selected in On the curve. The value placed in the button named and multiply by will be used during the computation. This allows for instance to invert the sign of the velocity. Also checking the button named Reject zero values improves the computation of the mean value by not including unmeasured points (zero value).

- Accept will display the resulting profile.

- A mouse click on the legend displayed on the top panel, allows:

- to edit the legend

- to remove the profile

- Clicking on the Add button allows to add more profiles and therefore perform comparisons. Simply repeat the above procedure.

- Clicking the Save this comparison button not only save the displayed information (selected files and curves) but also allows to create an ASCII files containing the data values of each displayed curves. For each curve, the ASCII file contains 2 lines of calibrated data values in a floating format (in mm/s or other unit, depending the data). The first line giving the X values and the second line the Y values.

- Clicking the Get a comparison button allows to recall and display a saved comparison (*.cdp file).

Signal Processing S.A. - DOP3000/3010 user's manual

10 - 19

Storing and reading measures

10 - 20

Signal Processing S.A. - DOP3000/3010 user's manual