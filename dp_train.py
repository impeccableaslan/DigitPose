from dp_layers import DP
from dp_batch import Batch
from dp_houghVL import Hough
import numpy as np
import os
import tensorflow as tf
import pathlib
import cv2

def train_DP():
    ''' Load Snapshots '''
    imagedir = os.path.join(".\\data", "DigitPose-Frame", "Snapshots")
    imagedir = pathlib.Path(imagedir)
    image_paths = list(imagedir.glob('*.*'))
    image_paths = [str(path) for path in image_paths]

    ''' Load Groundtruths '''
    gtdir = os.path.join(".\\data", "DigitPose-Frame", "Groundtruths")
    gtdir = pathlib.Path(gtdir)
    gt_paths = list(gtdir.glob('*'))
    gt_paths = [str(path) for path in gt_paths]

    ''' Load Orientations '''
    oriendir = os.path.join(".\\data", "DigitPose-Frame", "Orientations")
    oriendir = pathlib.Path(oriendir)
    orien_paths = list(oriendir.glob('*'))
    orien_paths = [str(path) for path in orien_paths]

    ''' Load Points '''
    pts_dir = os.path.join(".\\data", "DigitPose-Frame", "Points")
    pts_dir = pathlib.Path(pts_dir)
    pts_paths = list(pts_dir.glob('*'))
    pts_paths = [str(path) for path in pts_paths]

    ''' Load Numbers '''
    nums_dir = os.path.join(".\\data", "DigitPose-Frame", "Numbers")
    nums_dir = pathlib.Path(nums_dir)
    num_paths = list(nums_dir.glob('*'))
    num_paths = [str(path) for path in num_paths]

    ''' Create CNN '''
    n_classes = 2
    n_points = 1
    debug = False
    IMAGE_HW = 224
    model_dir = "./data/imagenet-vgg-verydeep-19.mat"
    poseCNN = DP(debug=debug, n_classes=n_classes, n_points=n_points, IMAGE_WH=IMAGE_HW, model_dir=model_dir)
    TRAIN_MODE = ["labels", "centers", "pose"]
    
    ''' Create Batch '''
    batch = Batch(im_paths=image_paths, im_labels=gtdir, im_orientations=oriendir, im_coordinates=pts_dir, im_numbers=nums_dir,
                  n_classes=n_classes, n_points=n_points)
    N_epochs = 10000000
    N_eval = 10

    ''' Create Saver '''
    save_file = "./models/dp_train_new_1st/model.ckpt"
    LOAD_MODEL = True
    FIRST = True
    if FIRST and LOAD_MODEL:
        PREV_TRAIN_MODE = TRAIN_MODE[0:-1]
        poseCNN.attach_saver(PREV_TRAIN_MODE)
    else:
        poseCNN.attach_saver(TRAIN_MODE)
    
    ''' Create TF session '''
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    with tf.Session(config=config) as sess:
        if not LOAD_MODEL:
            sess.run(tf.global_variables_initializer())
        else:
            if FIRST:
                sess.run(tf.global_variables_initializer())
                poseCNN.saver_tf.restore(sess, save_file)
                poseCNN.attach_saver(TRAIN_MODE)
            else:
                sess.run(tf.global_variables_initializer())
                for branch in TRAIN_MODE:
                    poseCNN.attach_saver([branch])
                    poseCNN.saver_tf.restore(sess, save_file)
                poseCNN.attach_saver(TRAIN_MODE)
        for epochs in range(N_epochs):
            RGB, LABEL, stack_centerxyz, oriens, coords = batch.get_image_and_label_ALL()
            if TRAIN_MODE[-1] == "labels":
                feed_dict = {poseCNN.image: RGB, poseCNN.labels_annotation: LABEL, poseCNN.labels_keep_probability: 0.85}
                sess.run(poseCNN.labels_train_op, feed_dict=feed_dict)
            elif TRAIN_MODE[-1] == "centers":
                feed_dict = {poseCNN.image: RGB, poseCNN.centers_annotation: stack_centerxyz, poseCNN.centers_keep_probability: 0.85}
                sess.run(poseCNN.centers_train_op, feed_dict=feed_dict)
            elif TRAIN_MODE[-1] == "pose":
                feed_dict = {poseCNN.image: RGB, poseCNN.labels_keep_probability: 1.0, poseCNN.centers_keep_probability: 1.0}
                labels_pred, directions = sess.run([poseCNN.labels_pred, poseCNN.centers_pred], feed_dict=feed_dict)
                directions = np.moveaxis(directions[0], -1, 0)
                hough_layer = Hough(n_classes, IMAGE_HW)
                hough_layer.cast_votes(labels_pred[0], directions[0], directions[1], directions[2])
                rois = hough_layer.get_rois()
                feed_dict = {poseCNN.image: RGB, poseCNN.rois: rois, poseCNN.pose_annotation: oriens, poseCNN.coordinates: coords, poseCNN.pose_keep_probability: 0.85}
                sess.run(poseCNN.pose_train_op, feed_dict=feed_dict)
            else:
                print("Invalid TRAIN MODE")

            if (epochs + 1) % 100 == 0:
                if TRAIN_MODE[-1] == "labels":
                    avg_labels_acc = 0
                    RGB, LABEL, stack_centerxyz, oriens, coords = batch.get_image_and_label_ALL()
                    feed_dict_labels = {poseCNN.image: RGB, poseCNN.labels_annotation: LABEL, poseCNN.labels_keep_probability: 1.0}
                    labels_acc = poseCNN.labels_pred_accuracy.eval(feed_dict=feed_dict_labels)
                    avg_labels_acc += labels_acc
                    print("Epoch:", epochs, "|  Labels accuracy =", avg_labels_acc / 1.0)
                elif TRAIN_MODE[-1] == "centers":
                    avg_centers_acc = 0
                    RGB, LABEL, stack_centerxyz, oriens, coords = batch.get_image_and_label_ALL()
                    feed_dict_centers = {poseCNN.image: RGB, poseCNN.centers_annotation: stack_centerxyz, poseCNN.centers_keep_probability: 1.0}
                    centers_acc = poseCNN.centers_pred_accuracy.eval(feed_dict=feed_dict_centers)
                    avg_centers_acc += centers_acc
                    print("Epoch:", epochs, "|  Centers accuracy =", avg_centers_acc / 1.0)
                elif TRAIN_MODE[-1] == "pose":
                    feed_dict = {poseCNN.image: RGB, poseCNN.labels_keep_probability: 1.0, poseCNN.centers_keep_probability: 1.0}
                    labels_pred, directions = sess.run([poseCNN.labels_pred, poseCNN.centers_pred], feed_dict=feed_dict)
                    directions = np.moveaxis(directions[0], -1, 0)
                    hough_layer = Hough(n_classes, IMAGE_HW)
                    hough_layer.cast_votes(labels_pred[0], directions[0], directions[1], directions[2])
                    rois = hough_layer.get_rois()
                    feed_dict = {poseCNN.image: RGB, poseCNN.rois: rois, poseCNN.pose_annotation: oriens, poseCNN.coordinates: coords, poseCNN.pose_keep_probability: 1.0}
                    pose_acc = sess.run(poseCNN.pose_pred_accuracy, feed_dict=feed_dict)
                    print("Epoch:", epochs, "|  Pose accuracy =", pose_acc)
                poseCNN.saver_tf.save(sess, save_file)
                print("Model saved")

train_DP()
