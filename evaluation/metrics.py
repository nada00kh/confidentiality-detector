from src.detectors.regex_detector import (
    PATTERNS,
    detect_entities
)

def calculate_scores(tp,fp,fn):
    precision = tp / (tp+fp) if tp + fp else 0.0
    recall = tp / (tp+fn) if tp +fn else 0.0

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0.0
    )

    return {
        "precision": precision,
        "recall": recall,   
        "f1": f1
    }
# to compare the regex results with Site data
def evaluate(rows):
    selected_labels = set(PATTERNS)

    # we have two counters one for the s=entity level task and the other for the message level task
    entity_tp = entity_fp = entity_fn = 0
    msg_tp = msg_fp = msg_fn = msg_tn = 0
    total = 0

    
    for row in rows:
        total += 1
        text = row["text"]

        # Ground truth from annotations
        gold = {
            (e["label"], int(e["start"]), int(e["end"]))
            for e in row["entities"]
            if e["label"] in selected_labels # we save entity of it is included in our scope 
        } 

        # Predictions from the regex
        predictions = detect_entities(text)
        # we converted predictions so we can compare them with the ground truth
        predicted = {
            (e["label"], int(e["start"]), int(e["end"]))
            for e in predictions
        }

        entity_tp += len(gold & predicted) # Itersection between two sets
        entity_fp += len(predicted - gold) # Difference
        entity_fn += len(gold - predicted) 

        gold_block = bool(gold)
        predicted_block = bool(predicted)

        if gold_block and predicted_block:
            msg_tp += 1
        elif not gold_block and predicted_block:
            msg_fp += 1 
        elif gold_block and not predicted_block:
            msg_fn += 1
        else:
            msg_tn +=1

    message_accuracy = (
        (msg_tp + msg_tn) / total if total else 0.0
    )
    

    return {
        "samples": total,
        "entity_micro": calculate_scores(entity_tp, entity_fp, entity_fn), # Micro-averaged Entity Metric it sums all tp fp and fn from all classes before calculating metrics
        "message": {
            **calculate_scores(msg_tp, msg_fp, msg_fn), # ** means unpacking 
            "accuracy": message_accuracy,
            "TP": msg_tp,
            "FP": msg_fp,
            "FN": msg_fn,
            "TN": msg_tn
           }
    }
# macro-F1: it calculate f-1 for each class seperatly then take the avarage for all classes.