

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from collections import defaultdict

import logging
import time
import numpy as np

from detectron.utils.timer import Timer
import detectron.core.test_engine as infer_engine
import detectron.datasets.dummy_datasets as dummy_datasets
import detectron.utils.c2 as c2_utils

c2_utils.import_detectron_ops()



def convert_from_cls_format(cls_boxes, cls_segms, cls_keyps):
    """Convert from the class boxes/segms/keyps format generated by the testing
    code.
    """
    box_list = [b for b in cls_boxes if len(b) > 0]
    if len(box_list) > 0:
        boxes = np.concatenate(box_list)
    else:
        boxes = None
    if cls_segms is not None:
        segms = [s for slist in cls_segms for s in slist]
    else:
        segms = None
    if cls_keyps is not None:
        keyps = [k for klist in cls_keyps for k in klist]
    else:
        keyps = None
    classes = []
    for j in range(len(cls_boxes)):
        classes += [j] * len(cls_boxes[j])
    return boxes, segms, keyps, classes


class DensePoseModel:

    def __init__(self, weights=""):
        self.model=None
        self.dummy_coco_dataset=None
        self.construct_model(weights)

    def construct_model(self,weights):
        logger = logging.getLogger(__name__)

        self.model = infer_engine.initialize_model_from_cfg(weights)
        self.dummy_coco_dataset = dummy_datasets.get_coco_dataset()
        logger.info("Model created\n\n\n")

    def form_IUV_mask(self,im, boxes, segms=None, keypoints=None, body_uv=None, thresh=0.9):


        if isinstance(boxes, list):
            boxes, segms, keypoints, classes = convert_from_cls_format(
                boxes, segms, keypoints)

        if boxes is None or boxes.shape[0] == 0 or max(boxes[:, 4]) < thresh:
            return

        #   DensePose Visualization Starts!!
        ##  Get full IUV image out
        IUV_fields = body_uv[1]
        #
        All_Coords = np.zeros(im.shape)
        All_inds = np.zeros([im.shape[0], im.shape[1]])
        K = 26
        ##
        inds = np.argsort(boxes[:, 4])
        ##
        for i, ind in enumerate(inds):
            entry = boxes[ind, :]
            if entry[4] > 0.65:
                entry = entry[0:4].astype(int)
                ####
                output = IUV_fields[ind]
                ####
                All_Coords_Old = All_Coords[entry[1]: entry[1] + output.shape[1], entry[0]:entry[0] + output.shape[2],
                                 :]
                All_Coords_Old[All_Coords_Old == 0] = output.transpose([1, 2, 0])[All_Coords_Old == 0]
                All_Coords[entry[1]: entry[1] + output.shape[1], entry[0]:entry[0] + output.shape[2],
                :] = All_Coords_Old
                ###
                CurrentMask = (output[0, :, :] > 0).astype(np.float32)
                All_inds_old = All_inds[entry[1]: entry[1] + output.shape[1], entry[0]:entry[0] + output.shape[2]]
                All_inds_old[All_inds_old == 0] = CurrentMask[All_inds_old == 0] * i
                All_inds[entry[1]: entry[1] + output.shape[1], entry[0]:entry[0] + output.shape[2]] = All_inds_old
        #
        All_Coords[:, :, 1:3] = 255. * All_Coords[:, :, 1:3]
        All_Coords[All_Coords > 255] = 255.
        All_Coords = All_Coords.astype(np.uint8)
        return All_Coords

    def predict_iuvs(self,imlist):
        #images in bgr not rgb

        IUVs_List=[]
        logger = logging.getLogger(__name__)
        timers = defaultdict(Timer)
        t = time.time()

        height, width, layers = imlist[0].shape
        for count,im in enumerate(imlist):
            with c2_utils.NamedCudaScope(0):
                cls_boxes, cls_segms, cls_keyps, cls_bodys = infer_engine.im_detect_all(
                    self.model, im, None, timers=timers
                )


            logger.info('Inference time: {:.3f}s'.format(time.time() - t))
            for k, v in timers.items():
                logger.info(' | {}: {:.3f}s'.format(k, v.average_time))

            IUVs = self.form_IUV_mask(
                im[:, :, ::-1],  # BGR -> RGB for visualization
                cls_boxes,
                cls_segms,
                cls_keyps,
                cls_bodys,
                thresh=0.7,
            )
            if IUVs is None:
                print("frame missing")
                if count != 0:
                    IUVs = IUVs_List[-1]
                else:
                    IUVs = np.zeros((height, width, 3), dtype=np.uint8)

            if IUVs.shape != tuple((height, width, 3)):
                print("shape mismatch occured. Shape expected {} Shape received {}".format((height, width, 3),
                                                                                           IUVs.shape))
                IUVs = np.zeros((height, width, 3), dtype=np.uint8)



            IUVs_List.append(IUVs)
        return IUVs_List
