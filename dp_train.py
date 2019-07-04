from dp_layers import DP
from dp_batch import Batch
from dp_houghVL import Hough
import numpy as np
import os
import tensorflow as tf
import pathlib
import cv2

def train_DP():
    ''' Load images '''
    imagedir = os.path.join(".\\data", "DigitPose-Frame", "Snapshots")
    imagedir = pathlib.Path(imagedir)
    image_paths = list(imagedir.glob('*.*'))
    image_paths = [str(path) for path in image_paths]

    ''' Create labels '''
    labelsdir = os.path.join(".\\data", "DigitPose-Frame", "Groundtruths")
    labelsdir = pathlib.Path(labelsdir)
    label_paths = list(labelsdir.glob('*'))
    label_paths = [str(path) for path in label_paths]

    ''' Create labels2 '''
    labelsdir2 = os.path.join(".\\data", "DigitPose-Frame", "Orientations")
    labelsdir2 = pathlib.Path(labelsdir2)
    label_paths2 = list(labelsdir2.glob('*'))
    label_paths2 = [str(path) for path in label_paths2]

    ''' Create labels3 '''
    labelsdir3 = os.path.join(".\\data", "DigitPose-Frame", "Points")
    labelsdir3 = pathlib.Path(labelsdir3)
    label_paths3 = list(labelsdir3.glob('*'))
    label_paths3 = [str(path) for path in label_paths3]

    ''' Create CNN '''
    n_classes = 2
    n_points = 1
    debug = False
    IMAGE_HW = 224
    model_dir = "./data/imagenet-vgg-verydeep-19.mat"
    poseCNN = DP(debug=debug, n_classes=n_classes, n_points=n_points, IMAGE_WH=IMAGE_HW, model_dir=model_dir)
    TRAIN_MODE = "labels"
    
    ''' Create Batch '''
    batch = Batch(image_paths, label_paths, label_paths2, label_paths3, n_classes=n_classes, n_points=n_points)
    N_epochs = 10000000
    N_eval = 10

    ''' Create Saver '''
    poseCNN.attach_saver()
    save_file = "./models/dp_train_new_1st/model.ckpt"
    LOAD_MODEL = False

    ''' Create TF session '''
    gpu_options = tf.GPUOptions(polling_inactive_delay_msecs=1000000, allow_growth=True)
    cfg = tf.ConfigProto(gpu_options=gpu_options)
    with tf.Session(config=cfg) as sess:
        if not LOAD_MODEL:
            sess.run(tf.global_variables_initializer())
        else:
            poseCNN.saver_tf.restore(sess, save_file)
        for epochs in range(N_epochs):
            RGB, LABEL, stack_centerxyz, oriens, coords = batch.get_image_and_label_ALL()
            if TRAIN_MODE == "labels":
                feed_dict = {poseCNN.image: RGB, poseCNN.labels_annotation: LABEL, poseCNN.labels_keep_probability: 0.85}
                sess.run(poseCNN.labels_train_op, feed_dict=feed_dict)
            elif TRAIN_MODE == "centers":
                feed_dict = {poseCNN.image: RGB, poseCNN.centers_annotation: stack_centerxyz, poseCNN.centers_keep_probability: 0.85}
                sess.run(poseCNN.centers_train_op, feed_dict=feed_dict)
            elif TRAIN_MODE == "pose":
                feed_dict = {poseCNN.image: RGB}
                labels_pred, directions = sess.run([poseCNN.labels_pred, poseCNN.centers_pred], feed_dict=feed_dict)
                directions = np.moveaxis(directions[0], -1, 0)
                hough_layer = Hough(n_classes, IMAGE_HW)
                hough_layer.cast_votes(labels_pred[0], directions[0], directions[1], directions[2])
                rois = hough_layer.get_rois()
                feed_dict = {poseCNN.image: RGB, poseCNN.rois: [rois], poseCNN.pose_annotation: oriens, poseCNN.coordinates: coords, poseCNN.pose_keep_probability: 0.85}
                sess.run(poseCNN.pose_train_op, feed_dict=feed_dict)
            else:
                print("Invalid TRAIN MODE")

            if (epochs + 1) % 100 == 0:
                if TRAIN_MODE == "labels":
                    avg_labels_acc = 0
                    for e in range(N_eval):
                        RGB, LABEL, stack_centerxyz, oriens, coords = batch.get_image_and_label_ALL()
                        feed_dict_labels = {poseCNN.image: RGB, poseCNN.labels_annotation: LABEL, poseCNN.labels_keep_probability: 1.0}
                        labels_acc = poseCNN.labels_pred_accuracy.eval(feed_dict=feed_dict_labels)
                        avg_labels_acc += labels_acc
                    print("Epoch:", epochs, "|  Labels accuracy =", avg_labels_acc / 10.0)
                elif TRAIN_MODE == "centers" and not poseCNN.use_tb_summary:
                    avg_centers_acc = 0
                    for e in range(N_eval):
                        RGB, LABEL, stack_centerxyz, oriens, coords = batch.get_image_and_label_ALL()
                        feed_dict_centers = {poseCNN.image: RGB, poseCNN.centers_annotation: stack_centerxyz, poseCNN.centers_keep_probability: 1.0}
                        centers_acc = poseCNN.centers_pred_accuracy.eval(feed_dict=feed_dict_centers)
                        avg_centers_acc += centers_acc
                    print("Epoch:", epochs, "|  Labels accuracy =", avg_centers_acc / 10.0)
                elif TRAIN_MODE == "pose" and not poseCNN.use_tb_summary:
                    feed_dict = {poseCNN.image: RGB}
                    labels_pred, directions = sess.run([poseCNN.labels_pred, poseCNN.centers_pred], feed_dict=feed_dict)
                    directions = np.moveaxis(directions[0], -1, 0)
                    hough_layer = Hough(n_classes, IMAGE_HW)
                    hough_layer.cast_votes(labels_pred[0], directions[0], directions[1], directions[2])
                    rois = hough_layer.get_rois()
                    feed_dict = {poseCNN.image: RGB, poseCNN.rois: [rois], poseCNN.pose_annotation: oriens, poseCNN.coordinates: coords, poseCNN.pose_keep_probability: 1.0}
                    pose_acc = sess.run(poseCNN.pose_pred_accuracy, feed_dict=feed_dict)
                    print("Epoch:", epochs, "|  Labels accuracy =", pose_acc)
                elif not poseCNN.use_tb_summary:
                    print("Invalid TRAIN MODE")

                poseCNN.saver_tf.save(sess, save_file)

train_DP()