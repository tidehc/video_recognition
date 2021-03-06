"""
Generate video samples.
"""

import argparse
import os
import random
import time

import cv2
import numpy as np

from config import (BACKD_VIDEO_DIR_PATH, CNN_FRAME_SIZE, CNN_VIDEO_HEIGHT,
                    CNN_VIDEO_WIDTH, FORGD_VIDEO_DIR_PATH, FRAMES_BY_SECOND,
                    MAX_SAMPLES_BY_VIDEO, PRELOAD_SAMPLES,
                    TRAIN_TEST_SPLIT_RATIO)
from utils.path_utils import get_files_in_directory


def get_labeled_video(forgd_video_dir, backd_video_dir, dataset="train",
                      split_ratio=TRAIN_TEST_SPLIT_RATIO):
    """
    Get video paths by label.
    """

    # Create dataset file lists.
    labels = ["Background"]
    data = []

    # Add background videos.
    video_paths = get_files_in_directory(backd_video_dir)
    split_index = int(len(video_paths) * split_ratio)

    if dataset == "train":
        data.append(video_paths[:split_index])
    else:
        split_index_end = int((split_index + len(video_paths)) / 2)

        if dataset == "validation":
            data.append(video_paths[split_index:split_index_end])
        else:
            data.append(video_paths[split_index_end:])

    # Add foreground videos.
    labels.extend(get_labels(forgd_video_dir))
    total_labels = len(labels)

    for index_label in range(1, total_labels):
        label_dir = forgd_video_dir + "/" + labels[index_label]
        video_paths = get_files_in_directory(label_dir)

        if len(video_paths) > 0:
            split_index = int(len(video_paths) * split_ratio)

            if dataset == "train":
                data.append(video_paths[:split_index])
            else:
                split_index_end = int((split_index + len(video_paths)) / 2)

                if dataset == "validation":
                    data.append(video_paths[split_index:split_index_end])
                else:
                    data.append(video_paths[split_index_end:])

    return data, labels


def sample_generator(forgd_video_dir, backd_video_dir, dataset="train",
                     split_ratio=TRAIN_TEST_SPLIT_RATIO,
                     frame_size=CNN_FRAME_SIZE, width=CNN_VIDEO_WIDTH,
                     height=CNN_VIDEO_HEIGHT, preload_samples=PRELOAD_SAMPLES,
                     fps=FRAMES_BY_SECOND,
                     max_samples_by_video=MAX_SAMPLES_BY_VIDEO):
    """
    Generate sample from video directory.
    """

    paths, labels = get_labeled_video(forgd_video_dir, backd_video_dir,
                                      dataset, split_ratio)
    total_labels = len(labels)
    labels = []
    backd_gens = []
    forgd_gens = []

    if dataset == "test":
        augment_data = False
    else:
        augment_data = True

    preload_samples = int(preload_samples / 2)
    count_forgd_gen_labels = dict()

    for i in range(total_labels):
        if len(paths[i]) > 0:
            if augment_data:
                if i > 0:
                    labels.append(i)
                else:
                    for _j in range(preload_samples):
                        video_path = paths[0][random.randint(
                            0, len(paths[0]) - 1)]
                        backd_gens.append(
                            frames_generator(video_path, frame_size,
                                             width, height, augment_data, fps,
                                             max_samples_by_video))
            else:
                labels.append(i)

    while len(forgd_gens) > 0 or len(labels) > 0:
        if augment_data:
            backd_frames = None

            while backd_frames is None:
                try:
                    index_gen = random.randint(0, len(backd_gens) - 1)
                    backd_frames = next(backd_gens[index_gen])
                except StopIteration:
                    backd_frames = None
                    video_path = paths[0][random.randint(0,
                                                         len(paths[0]) - 1)]
                    backd_gens[index_gen] = frames_generator(
                        video_path, frame_size, width, height, augment_data,
                        fps, max_samples_by_video)

        if len(forgd_gens) > 0:
            select_gen = random.choice(forgd_gens)

            try:
                if augment_data:
                    forgd_frames = next(select_gen[1])
                    sample_label = np.zeros(len(paths), dtype=np.uint8)
                    sample_label[0] = 1
                    sample_label[select_gen[0]] = 1
                    yield forgd_frames, backd_frames, sample_label
                else:
                    forgd_frames = next(select_gen[1])
                    sample_label = np.zeros(len(paths), dtype=np.uint8)
                    if select_gen[0] != 0:
                        sample_label[0] = 1
                        sample_label[select_gen[0]] = 1

                    yield forgd_frames, sample_label
            except StopIteration:
                forgd_gens.remove(select_gen)

                if len(paths[select_gen[0]]) == 0:
                    if augment_data:
                        count_forgd_gen_labels[select_gen[0]] -= 1

                        if count_forgd_gen_labels[select_gen[0]] <= 0:
                            return
                    elif select_gen[0] in labels:
                        labels.remove(select_gen[0])

        while len(forgd_gens) < preload_samples and len(labels) > 0:
            select_label = random.choice(labels)

            if len(paths[select_label]) > 0:
                video_path = paths[select_label].pop(
                    random.randint(0, len(paths[select_label]) - 1))
                forgd_gens.append((select_label,
                                   frames_generator(video_path,
                                                    frame_size, width,
                                                    height, augment_data,
                                                    fps,
                                                    max_samples_by_video)))

                if augment_data:
                    if select_label in count_forgd_gen_labels.keys():
                        count_forgd_gen_labels[select_label] += 1
                    else:
                        count_forgd_gen_labels[select_label] = 1
            elif select_label in labels:
                labels.remove(select_label)


def frames_generator(video_path, frame_size=CNN_FRAME_SIZE,
                     width=CNN_VIDEO_WIDTH, height=CNN_VIDEO_HEIGHT,
                     augment_data=True, fps=FRAMES_BY_SECOND,
                     max_samples_by_video=MAX_SAMPLES_BY_VIDEO):
    """
    Generate frame from video_path.
    """

    ext = os.path.basename(video_path).split(".")[-1]
    video_adjusted_path = video_path.replace("." + ext, "_adjusted" + ".avi")
    video_adjusted = False
    samples_by_video = 0

    if os.path.exists(video_adjusted_path):
        video_path = video_adjusted_path
        video_adjusted = True

    if video_adjusted or os.path.exists(video_path):
        # Capture data from video.
        cap = cv2.VideoCapture(video_path)

        if cap.isOpened():
            video_fps = cap.get(cv2.CAP_PROP_FPS)
            frame_index = 0
            video_index = 0
            jump_random = 0
            video_time = 0
            expected_frame_index = 0
            expected_time = 0
            frame_width = int(cap.get(3))
            frame_height = int(cap.get(4))

            if frame_height >= height and frame_width >= width:
                start_y = random.randint(0, frame_height - height)
                finish_y = start_y + height
                start_x = random.randint(0, frame_width - width)
                finish_x = start_x + width
            else:
                return

            frames = []

            while True:
                delta = expected_time - video_time

                if delta >= 0:
                    ret, frame = cap.read()

                    if not ret:
                        break

                    if augment_data:
                        jump_random -= 1

                    video_index += 1.0
                    video_time = video_index / video_fps
                else:
                    expected_frame_index += 1.0
                    expected_time = expected_frame_index / fps

                    if jump_random <= 0:
                        if len(frames) >= frame_size:
                            frames.pop(0)

                        frames.append(frame[start_y:finish_y,
                                            start_x:finish_x])
                        frame_index += 1

                        # # Display the resulting frame.
                        # print(delta)
                        # cv2.imshow('frame', frame)
                        #
                        # # Press Q on keyboard to stop recording.
                        # if cv2.waitKey(1) & 0xFF == ord('q'):
                        #     break

                        if frame_index >= frame_size:
                            if augment_data:
                                jump_random = random.randint(
                                    0, frame_size * 2)

                            frame_index = 0
                            np_frames = np.array(frames)
                            yield np_frames

                            samples_by_video += 1
                            if samples_by_video >= max_samples_by_video:
                                break

                            start_y = random.randint(0, frame_height - height)
                            finish_y = start_y + height
                            start_x = random.randint(0, frame_width - width)
                            finish_x = start_x + width

        # When everything done, release the video capture.
        cap.release()


def get_labels(video_dir):
    """
    Get labels from video directory.
    """

    label_dirs = sorted(os.listdir(video_dir))

    return label_dirs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Generate random video samples.')
    parser.add_argument('-f', '--foreground-video-dir', type=str,
                        default=FORGD_VIDEO_DIR_PATH,
                        help='The foreground video directory.')
    parser.add_argument('-b', '--background-video-dir', type=str,
                        default=BACKD_VIDEO_DIR_PATH,
                        help='The background video directory.')
    parser.add_argument('-s', '--train-test-split-ratio', type=float,
                        default=TRAIN_TEST_SPLIT_RATIO,
                        help='The ratio to split the dataset in'
                             'train and test.')
    parser.add_argument('-d', '--frame-size', type=int,
                        default=CNN_FRAME_SIZE, help='The frame size.')
    parser.add_argument('-w', '--width', type=int, default=CNN_VIDEO_WIDTH,
                        help='The video width.')
    parser.add_argument('-e', '--height', type=int, default=CNN_VIDEO_HEIGHT,
                        help='The video height.')
    parser.add_argument('-p', '--fps', type=int, default=FRAMES_BY_SECOND,
                        help='The input video file.')
    parser.add_argument('-m', '--max-samples-by-video', type=int,
                        default=MAX_SAMPLES_BY_VIDEO,
                        help='The input video file.')

    args = parser.parse_args()
    forgd_video_dir = args.foreground_video_dir
    backd_video_dir = args.background_video_dir
    max_samples_by_video = args.max_samples_by_video
    frame_size = args.frame_size
    height = args.height
    width = args.width
    train_test_split_ratio = args.train_test_split_ratio
    fps = args.fps
    labels = ["Background"]
    labels.extend(get_labels(forgd_video_dir))

    # Create generator.
    generator = sample_generator(forgd_video_dir, backd_video_dir,
                                 split_ratio=train_test_split_ratio,
                                 frame_size=frame_size, width=width,
                                 height=height, dataset="train", fps=fps,
                                 max_samples_by_video=max_samples_by_video)

    # Generate samples.
    last_sample = False
    i = 0

    while not last_sample:
        try:
            data = next(generator)
            if len(data) == 3:
                forgd_frames, backd_frames, label = data
                print(labels[1 + np.argmax(label[1:])])

                for i in range(forgd_frames.shape[0]):
                    forgd_frame = forgd_frames[i]
                    backd_frame = backd_frames[i]
                    cv2.imshow('frame',
                               np.vstack((forgd_frame, backd_frame)))

                    time.sleep(0.01)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
            else:
                forgd_frames, label = data

                if label[0] == 1:
                    print(labels[1 + np.argmax(label[1:])])
                else:
                    print("Background")

                for i in range(forgd_frames.shape[0]):
                    forgd_frame = forgd_frames[i]
                    cv2.imshow('frame', forgd_frame)

                    time.sleep(0.01)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break

        except StopIteration:
            last_sample = True
