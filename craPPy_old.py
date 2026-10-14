import cv2
import os
import numpy as np
from PyQt6.QtWidgets import QApplication, QFileDialog



def load_presentation():
    #app = QApplication([])
    pres_path = '/home/yann/Documents/workspace/DAWN/posters_and_slides/presentations_cv/PoS' #QFileDialog.getExistingDirectory(None, "Select presentation directory")
    # while (("slides","transi") not in os.listdir(pres_path)):
    #     print("The selected dir is not a presentation directory")
    #     pres_path = QFileDialog.getExistingDirectory(None, "Select presentation directory")
    slides = load_pngs(pres_path+"/slides/")
    transi = load_transi(pres_path+"/transi/")
    tpara  = np.loadtxt(pres_path+"/transi.para",dtype=np.int32)
    return slides,transi, tpara

def load_transi(transi_path):
    transi = []
    transi_dirs = [f for f in os.listdir(transi_path)]
    transi_dirs.sort()
    for t in transi_dirs:
        transi.append(load_pngs(transi_path+t+"/"))
    return transi

def load_pngs(path_dir):
    data = []
    png_files = [f for f in os.listdir(path_dir) if f.lower().endswith('.png')]
    if (len(png_files)> 0):
        png_files.sort()  # Sort the files to ensure consistent order
        for png in png_files:
            img = cv2.imread(path_dir+png,cv2.IMREAD_UNCHANGED)
            if img is not None:
                data.append(img)
            else:
                print(f"Warning: Could not read image {path_dir+png}")
        return data
    else:
        return None

    


def create_transition_frames(slide1, slide2, num_frames=10):
    """Create transition frames between two slides."""
    transition_frames = []
    for i in range(num_frames):
        alpha = i / num_frames
        blended_frame = cv2.addWeighted(slide1, 1 - alpha, slide2, alpha, 0)
        transition_frames.append(blended_frame)
    return transition_frames


def show_slide_with_transition(revert=False,static = False):
    """Show the current slide with transition from the previous slide."""
    global intransi,slides,transitions,tpara,csld,ctr
    static = static or ctr < 0 # only when cycling from last to first and at the first slide
    if not(static):
        intransi = True
        if (revert):
            transition_frames = transitions[ctr][::-1] # revert the table to play backward
        else:
            transition_frames = transitions[ctr]

        for frame in transition_frames:
            cv2.imshow('Slide Show', frame)
            key = cv2.waitKey(tpara[ctr]) & 0xFF
            if key !=255: # Adjust the delay to control the speed of the transition
                event_handler(key)    
                break
    cv2.imshow('Slide Show', slides[csld])
    intransi = False

def mouse_click(event, x, y, 
                flags, param):
    global csld, ctr, slides, transitions, tpara, intransi
    static = False
    # to check if left mouse 
    # button was clicked
    if event == cv2.EVENT_LBUTTONDOWN:
        if not intransi:
            csld = (csld + 1) % nslides
            ctr  = (csld-1)
            print("forward",csld,ctr)
            if transitions[ctr] is None:
                static = True
            show_slide_with_transition(static=static)
        
    # to check if right mouse 
    # button was clicked
    if event == cv2.EVENT_RBUTTONDOWN:
        if (csld != 0):
            csld = (csld - 1) % nslides
            ctr = csld
            print("backward",csld,ctr)
            if transitions[ctr] is None:
                static = True
            if not intransi:
                show_slide_with_transition(revert=True,static=static)
            ctr = (csld -1)


def event_handler(key):
    global csld, ctr, slides, transitions, tpara, intransi
    static = False        

    match key:
        case 110 | 83 | 32| 86: # Forward (n,arrow_right,space)
            if not intransi:
                csld = (csld + 1) % nslides
                ctr  = (csld-1)
                print("forward",csld,ctr)
                if transitions[ctr] is None:
                    static = True
                show_slide_with_transition(static=static)

        case 112 | 81 | 98 | 233 | 85: # Backward (p,arrow_left)
            if (csld != 0):
                csld = (csld - 1) % nslides
                ctr = csld
                print("backward",csld,ctr)
                if transitions[ctr] is None:
                    static = True
                if not intransi:
                    show_slide_with_transition(revert=True,static=static)
                ctr = (csld -1)

        case 113 | 27: #Break condition (q,esc)
            return False
        case _:
            print("Unknown key event:",key)
    return True

         


if __name__ == "__main__":
    #load slides
    slides,transitions,tpara = load_presentation()
    nslides = len(slides)
    ntransi = len(transitions)

    csld = 0
    ctr  = -1
    intransi = False

    #Main slide window creation
    cv2.namedWindow('Slide Show', cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty('Slide Show', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.setMouseCallback("Slide Show",mouse_click)
    show_slide_with_transition()

    while True:
        key = cv2.waitKey(0) & 0xFF
        if not event_handler(key):
            break

    cv2.destroyAllWindows()