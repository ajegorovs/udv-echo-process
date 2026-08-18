(* ::Package:: *)

(* :Title: TemporalProjections *)
(* :Context: TemporalProjections` *)
(* :Package Version: 1.1.0 *)
(* :Mathematica Version: 12.1+ *)
(* :Summary:
     Memory-bounded, chunk-wise temporal projections for single-channel images.
     Supports exact temporal Min, Max, Mean, and StandardDeviation projections.
*)

BeginPackage["TemporalProjections`"];

ClearAll[TemporalProjections];

TemporalProjections::usage =
  "TemporalProjections[images, opts] computes chunk-wise temporal projections \
for a nonempty list of identically sized, single-channel Image objects.\n\n\
TemporalProjections[getChunk, frameCount, opts] computes the same projections \
using a chunk-loading function getChunk[ids], allowing file-backed or otherwise \
streamed processing.\n\n\
The returned Association contains \"Count\", \"RawImages\", and \
\"DisplayImages\". Supported projections are \"Max\", \"Min\", \"Mean\", and \
\"StandardDeviation\".\n\n\
Options:\n\
  \"ChunkSize\" -> 32\n\
  \"WorkingType\" -> \"Real32\"\n\
  \"StandardDeviationConvention\" -> \"Sample\"\n\
  \"ShowProgress\" -> True";

Options[TemporalProjections] = {
   "ChunkSize" -> 32,
   "WorkingType" -> "Real32",
   "StandardDeviationConvention" -> "Sample",
   "ShowProgress" -> True
   };

TemporalProjections::empty =
  "No images were supplied.";

TemporalProjections::badchunk =
  "The chunk beginning at frame `1` did not return a nonempty list of images.";

TemporalProjections::notimage =
  "The chunk beginning at frame `1` contains something other than Image objects.";

TemporalProjections::channels =
  "All input images must be single-channel images.";

TemporalProjections::dimensions =
  "All input images must have identical dimensions.";

TemporalProjections::chunksize =
  "ChunkSize must be a positive integer.";

TemporalProjections::convention =
  "StandardDeviationConvention must be \"Sample\" or \"Population\".";


Begin["`Private`"];

ClearAll[
  temporalChunkState,
  mergeTemporalStates,
  finalizeTemporalState
  ];


temporalChunkState[chunk_List, workingType_] :=
 Module[
  {
   n,
   stack,
   minImage,
   maxImage,
   meanImage,
   meanArray,
   standardDeviationArray,
   m2Array
   },

  n = Length[chunk];

  stack = ColorCombine[chunk];

  If[
   workingType =!= Automatic,
   stack = Image[stack, workingType]
   ];

  minImage = ImageApply[Min, stack];
  maxImage = ImageApply[Max, stack];
  meanImage = ImageApply[Mean, stack];

  meanArray = ImageData[meanImage, "Real"];

  m2Array =
   If[
    n == 1,

    ConstantArray[0., Dimensions[meanArray]],

    standardDeviationArray =
     ImageData[
      ImageApply[StandardDeviation, stack],
      "Real"
      ];

    (n - 1.) standardDeviationArray^2
    ];

  <|
   "Count" -> n,
   "MinImage" -> minImage,
   "MaxImage" -> maxImage,
   "MeanArray" -> meanArray,
   "M2Array" -> m2Array
   |>
  ];


mergeTemporalStates[stateA_Association, stateB_Association] :=
 Module[
  {
   nA,
   nB,
   n,
   delta,
   mergedMean,
   mergedM2,
   mergedMin,
   mergedMax
   },

  nA = stateA["Count"];
  nB = stateB["Count"];
  n = nA + nB;

  delta =
   stateB["MeanArray"] -
    stateA["MeanArray"];

  mergedMean =
   stateA["MeanArray"] +
    delta N[nB/n];

  mergedM2 =
   stateA["M2Array"] +
    stateB["M2Array"] +
    delta^2 N[nA nB/n];

  mergedMin =
   ImageApply[
    Min,
    ColorCombine[
     {
      stateA["MinImage"],
      stateB["MinImage"]
      }
     ]
    ];

  mergedMax =
   ImageApply[
    Max,
    ColorCombine[
     {
      stateA["MaxImage"],
      stateB["MaxImage"]
      }
     ]
    ];

  <|
   "Count" -> n,
   "MinImage" -> mergedMin,
   "MaxImage" -> mergedMax,
   "MeanArray" -> mergedMean,
   "M2Array" -> mergedM2
   |>
  ];


finalizeTemporalState[state_Association, convention_String] :=
 Module[
  {
   n,
   denominator,
   varianceArray,
   rawImages
   },

  n = state["Count"];

  denominator =
   Switch[
    convention,
    "Sample", n - 1.,
    "Population", N[n]
    ];

  If[
   denominator <= 0,
   Return[$Failed]
   ];

  varianceArray =
   Clip[
    state["M2Array"]/denominator,
    {0., Infinity}
    ];

  rawImages =
   <|
    "Max" -> state["MaxImage"],
    "Min" -> state["MinImage"],
    "Mean" -> Image[state["MeanArray"], "Real"],
    "StandardDeviation" ->
     Image[Sqrt[varianceArray], "Real"]
    |>;

  <|
   "Count" -> n,
   "RawImages" -> rawImages,
   "DisplayImages" -> Map[ImageAdjust, rawImages]
   |>
  ];


TemporalProjections[images_List, opts : OptionsPattern[]] :=
 Module[
  {},

  If[
   images === {},
   Message[TemporalProjections::empty];
   Return[$Failed]
   ];

  TemporalProjections[
   Function[ids, images[[ids]]],
   Length[images],
   opts
   ]
  ];


TemporalProjections[
   getChunk_,
   frameCount_Integer?Positive,
   OptionsPattern[]
   ] :=
 Module[
  {
   chunkSize,
   workingType,
   convention,
   showProgress,
   dimensions = None,
   state = None,
   newState,
   chunk,
   stop,
   ids,
   chunkCount,
   chunkIndex = 0,
   currentStart = 0,
   currentStop = 0,
   startTime,
   processResult,
   failureTag = Unique["TemporalProjectionsFailure"],
   processChunks
   },

  chunkSize = OptionValue["ChunkSize"];
  workingType = OptionValue["WorkingType"];
  convention =
   OptionValue["StandardDeviationConvention"];
  showProgress = TrueQ[OptionValue["ShowProgress"]];

  If[
   ! IntegerQ[chunkSize] || chunkSize < 1,
   Message[TemporalProjections::chunksize];
   Return[$Failed]
   ];

  If[
   ! MemberQ[{"Sample", "Population"}, convention],
   Message[TemporalProjections::convention];
   Return[$Failed]
   ];

  chunkCount = Ceiling[frameCount/chunkSize];
  startTime = AbsoluteTime[];

  processChunks[] :=
   Catch[
    Do[
     chunkIndex++;
     currentStart = start;
     currentStop =
      Min[
       start + chunkSize - 1,
       frameCount
       ];

     stop = currentStop;
     ids = Range[currentStart, stop];
     chunk = getChunk[ids];

     If[
      ! ListQ[chunk] || chunk === {},
      Message[TemporalProjections::badchunk, currentStart];
      Throw[$Failed, failureTag]
      ];

     If[
      ! And @@ (ImageQ /@ chunk),
      Message[TemporalProjections::notimage, currentStart];
      Throw[$Failed, failureTag]
      ];

     If[
      ! And @@ ((ImageChannels[#] == 1) & /@ chunk),
      Message[TemporalProjections::channels];
      Throw[$Failed, failureTag]
      ];

     If[
      dimensions === None,
      dimensions = ImageDimensions[First[chunk]]
      ];

     If[
      ! And @@ ((ImageDimensions[#] === dimensions) & /@ chunk),
      Message[TemporalProjections::dimensions];
      Throw[$Failed, failureTag]
      ];

     newState =
      temporalChunkState[
       chunk,
       workingType
       ];

     state =
      If[
       state === None,
       newState,
       mergeTemporalStates[state, newState]
       ];

     Clear[chunk, newState],

     {start, 1, frameCount, chunkSize}
     ];

    Null,
    failureTag
    ];

  processResult =
   If[
    showProgress,

    Monitor[
     processChunks[],

     Column[
      {
       Row[
        {
         "Processing chunk ",
         chunkIndex,
         " of ",
         chunkCount
         }
        ],

       ProgressIndicator[
        chunkIndex,
        {0, chunkCount},
        ImageSize -> 350
        ],

       Row[
        {
         "Frames: ",
         currentStart,
         "\[Dash]",
         currentStop,
         " of ",
         frameCount
         }
        ],

       Row[
        {
         "Elapsed: ",
         NumberForm[
          AbsoluteTime[] - startTime,
          {Infinity, 1}
          ],
         " s"
         }
        ]
       },
      Spacings -> 0.6
      ]
     ],

    processChunks[]
    ];

  If[
   processResult === $Failed,
   Return[$Failed]
   ];

  finalizeTemporalState[
   state,
   convention
   ]
  ];


End[];

EndPackage[];
