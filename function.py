import skrf as rf

def load_s2p(filepath):
    try:
        network=rf.Network(filepath)
        return network
    except Exception as e:
        print(f"Erreur lors du chargement du fichier .s2p : {e}")
        return None
