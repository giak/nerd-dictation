#!/home/giak/Work/nerd-dictation/venv/bin/python
"""
Script de contrôle pour nerd-dictation, conçu pour être appelé depuis StreamDeck
"""

import os
import sys
import subprocess
import logging
import time
import signal
import traceback
from datetime import datetime
from pathlib import Path

def send_notification(title, message, urgency="normal"):
    """
    Envoie une notification desktop

    Args:
        title (str): Titre de la notification
        message (str): Message de la notification
        urgency (str): Niveau d'urgence (low, normal, critical)
    """
    try:
        subprocess.run(["notify-send", title, message, f"-u", urgency], check=False)
        return True
    except Exception as e:
        logging.error(f"Erreur lors de l'envoi de la notification: {str(e)}")
        return False

# Chemins absolus - répertoire où ce script se trouve
SCRIPT_DIR = Path("/home/giak/Work/nerd-dictation").resolve()
NERD_DICTATION = SCRIPT_DIR / "nerd-dictation"
VOSK_MODEL_DIR = SCRIPT_DIR / "model"
LOCK_FILE = Path("/tmp/nerd-dictation.lock")
COOKIE_FILE = Path("/tmp/nerd-dictation.cookie")
LOG_FILE = Path("/tmp/dictation_control.log")

# Assurons-nous que le répertoire de log existe
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Configuration du logging
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Enregistrer également les erreurs non gérées
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        # Ne pas logger les interruptions clavier
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logging.error("Exception non gérée:", exc_info=(exc_type, exc_value, exc_traceback))
    print("Une erreur inattendue s'est produite. Vérifiez le fichier log:", LOG_FILE)

sys.excepthook = handle_exception

def log(message, level="INFO"):
    """Log un message avec le niveau spécifié"""
    if level == "INFO":
        logging.info(message)
    elif level == "WARNING":
        logging.warning(message)
    elif level == "ERROR":
        logging.error(message)
    elif level == "DEBUG":
        logging.debug(message)

    # Afficher également dans la console pour le débogage
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [{level}] - {message}")

def run_command(cmd, shell=False, timeout=10):
    """Exécute une commande système et retourne le résultat"""
    try:
        if shell:
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        else:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return True, output
    except subprocess.CalledProcessError as e:
        return False, e.output
    except subprocess.TimeoutExpired:
        log(f"La commande a dépassé le délai d'attente de {timeout}s: {cmd}", "WARNING")
        return False, f"Délai d'attente dépassé ({timeout}s)"
    except Exception as e:
        log(f"Erreur lors de l'exécution de la commande {cmd}: {str(e)}", "ERROR")
        return False, str(e)

def find_dictation_processes():
    """Trouve tous les processus nerd-dictation en cours"""
    try:
        success, output = run_command("pgrep -f 'nerd-dictation begin'", shell=True)
        pids = []

        if success and output.strip():
            pids.extend(output.strip().split('\n'))

        # Vérifier aussi le fichier cookie
        if COOKIE_FILE.exists():
            try:
                with open(COOKIE_FILE, 'r') as f:
                    pid = f.read().strip()
                    if pid and pid not in pids:
                        pids.append(pid)
            except Exception as e:
                log(f"Erreur lors de la lecture du fichier cookie: {e}", "WARNING")

        return pids
    except Exception as e:
        log(f"Erreur lors de la recherche des processus: {e}", "ERROR")
        log(traceback.format_exc(), "DEBUG")
        return []

def stop_media_playback():
    """Arrête la lecture média en cours via xdotool ou playerctl"""
    try:
        log("Arrêt de la lecture média...")

        # Essayer d'abord avec playerctl si disponible
        success, _ = run_command("which playerctl", shell=True)
        if success:
            # Vérifier si un média est en cours de lecture
            player_status, output = run_command("playerctl status 2>/dev/null || echo 'No players found'", shell=True)
            if player_status and "Playing" in output:
                run_command("playerctl pause", shell=True)
                log("Lecteur média mis en pause via playerctl")
                return True

        # Sinon utiliser xdotool
        success, output = run_command(["xdotool", "key", "XF86AudioPlay"])
        if success:
            log("Commande d'arrêt média envoyée via xdotool")
            return True
        else:
            log(f"Échec de l'envoi de la commande média via xdotool: {output}", "WARNING")
            return False
    except Exception as e:
        log(f"Erreur lors de l'arrêt de la lecture média: {e}", "ERROR")
        log(traceback.format_exc(), "DEBUG")
        return False

def start_dictation():
    """Démarre nerd-dictation"""
    try:
        log("Démarrage de la dictée...")

        # Vérifier si nerd-dictation existe
        if not NERD_DICTATION.exists():
            log(f"ERREUR: nerd-dictation non trouvé à {NERD_DICTATION}", "ERROR")
            return False

        # Vérifier si le modèle VOSK existe
        if not VOSK_MODEL_DIR.exists():
            log(f"ERREUR: Modèle VOSK non trouvé dans {VOSK_MODEL_DIR}", "ERROR")
            return False

        # Vérifier si la dictée est déjà en cours
        pids = find_dictation_processes()
        if pids:
            log(f"Des processus de dictée sont déjà en cours d'exécution: {', '.join(pids)}", "WARNING")
            stop_dictation()
            time.sleep(1)

        # Arrêter la lecture média avant de commencer
        stop_media_playback()

        # Démarrer nerd-dictation
        log("Lancement de nerd-dictation...")

        # Changement de répertoire pour s'assurer que les chemins relatifs fonctionnent correctement
        os.chdir(SCRIPT_DIR)

        # Configurer l'environnement explicitement
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SCRIPT_DIR)
        env["PATH"] = f"{SCRIPT_DIR}/venv/bin:{env.get('PATH', '')}"

        # Journaliser l'environnement pour le débogage
        log(f"PYTHONPATH: {env['PYTHONPATH']}", "DEBUG")
        log(f"PATH: {env['PATH']}", "DEBUG")
        log(f"PWD: {os.getcwd()}", "DEBUG")

        try:
            # Test en mode verbose pour le débogage - exécuter avec capture de sortie
            debug_file = "/tmp/nerd-dictation-debug.log"
            log(f"Test de démarrage avec capture de sortie dans {debug_file}", "DEBUG")

            with open(debug_file, 'w') as debug_out:
                test_cmd = [str(NERD_DICTATION), "begin", f"--vosk-model-dir={VOSK_MODEL_DIR}", "--verbose=2"]
                log(f"Commande de test: {' '.join(test_cmd)}", "DEBUG")
                try:
                    # Exécution synchrone pour tester et capturer la sortie
                    subprocess.run(
                        test_cmd,
                        stdout=debug_out,
                        stderr=debug_out,
                        env=env,
                        timeout=2,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    # C'est normal - cela signifie que le processus fonctionne sans se terminer
                    log("Le test initial semble réussi (timeout attendu)", "DEBUG")
                except Exception as e:
                    log(f"Erreur lors du test: {str(e)}", "WARNING")

            # Lire le fichier de débogage pour analyse
            try:
                with open(debug_file, 'r') as debug_in:
                    debug_output = debug_in.read()
                    log(f"Sortie de débogage: {debug_output[:500]}...", "DEBUG")  # Tronquer pour la lisibilité
            except Exception as e:
                log(f"Impossible de lire le fichier de débogage: {str(e)}", "WARNING")

            # Lancer le processus en arrière-plan pour l'utilisation réelle
            cmd = [str(NERD_DICTATION), "begin", f"--vosk-model-dir={VOSK_MODEL_DIR}"]
            log(f"Commande de démarrage réelle: {' '.join(cmd)}", "DEBUG")

            # Rediriger les sorties vers des fichiers pour analyse ultérieure
            stdout_file = open("/tmp/nerd-dictation-stdout.log", "w")
            stderr_file = open("/tmp/nerd-dictation-stderr.log", "w")

            process = subprocess.Popen(
                cmd,
                stdout=stdout_file,
                stderr=stderr_file,
                env=env,
                start_new_session=True  # Détacher le processus du terminal
            )

            # Attendre un peu pour s'assurer que le processus démarre correctement
            time.sleep(1)

            # Vérifier que le processus est bien démarré
            if process.poll() is None:  # None = encore en cours d'exécution
                pid = process.pid
                with open(LOCK_FILE, 'w') as f:
                    f.write(str(pid))
                log(f"Dictée démarrée avec le PID: {pid}")
                # Envoyer une notification
                send_notification("Nerd-Dictation", "Dictée démarrée", "normal")
                return True
            else:
                return_code = process.returncode
                log(f"Échec du démarrage de la dictée avec le code: {return_code}", "ERROR")

                # Tenter de lire les fichiers de sortie pour le diagnostic
                try:
                    stdout_file.close()
                    stderr_file.close()

                    with open("/tmp/nerd-dictation-stdout.log", "r") as f:
                        stdout_content = f.read()
                    with open("/tmp/nerd-dictation-stderr.log", "r") as f:
                        stderr_content = f.read()

                    if stdout_content:
                        log(f"Sortie standard: {stdout_content[:500]}...", "ERROR")
                    if stderr_content:
                        log(f"Sortie d'erreur: {stderr_content[:500]}...", "ERROR")
                except Exception as e:
                    log(f"Impossible de lire les fichiers de sortie: {str(e)}", "WARNING")

                return False
        except Exception as e:
            log(f"Erreur lors du démarrage de la dictée: {e}", "ERROR")
            log(traceback.format_exc(), "DEBUG")
            return False
    except Exception as e:
        log(f"Erreur générale lors du démarrage de la dictée: {e}", "ERROR")
        log(traceback.format_exc(), "DEBUG")
        return False

def kill_process(pid, force=False):
    """Tue un processus en envoyant SIGTERM ou SIGKILL si force=True"""
    try:
        pid = int(pid)
        try:
            # Vérifier si le processus existe
            os.kill(pid, 0)

            if force:
                log(f"Envoi de SIGKILL au processus {pid}...")
                os.kill(pid, signal.SIGKILL)
            else:
                log(f"Envoi de SIGTERM au processus {pid}...")
                os.kill(pid, signal.SIGTERM)

            return True
        except OSError:
            # Le processus n'existe pas
            return False
    except ValueError:
        log(f"PID invalide: {pid}", "WARNING")
        return False
    except Exception as e:
        log(f"Erreur lors de la terminaison du processus {pid}: {e}", "ERROR")
        return False

def stop_dictation():
    """Arrête nerd-dictation"""
    try:
        log("Arrêt de la dictée...")
        any_process_killed = False

        # Essayer d'abord la méthode propre avec nerd-dictation end
        log("Tentative d'arrêt propre avec nerd-dictation end...")
        os.chdir(SCRIPT_DIR)

        try:
            with open(os.devnull, 'w') as devnull:
                subprocess.run(
                    [str(NERD_DICTATION), "end"],
                    stdout=devnull,
                    stderr=devnull,
                    check=False,
                    timeout=5
                )
        except Exception as e:
            log(f"Erreur lors de l'arrêt propre: {e}", "WARNING")

        time.sleep(1)

        # Vérifier si un PID existe dans le fichier de verrouillage
        if LOCK_FILE.exists():
            try:
                with open(LOCK_FILE, 'r') as f:
                    pid = f.read().strip()

                if pid:
                    # Vérifier si le processus existe encore
                    try:
                        if kill_process(pid):
                            any_process_killed = True
                            time.sleep(0.5)

                            # Vérifier à nouveau et forcer si nécessaire
                            try:
                                os.kill(int(pid), 0)  # Le processus existe toujours
                                kill_process(pid, force=True)
                            except OSError:
                                pass  # Processus déjà terminé
                    except Exception as e:
                        log(f"Erreur lors de la terminaison du processus {pid}: {e}", "ERROR")

                # Supprimer le fichier de verrouillage
                LOCK_FILE.unlink(missing_ok=True)
            except Exception as e:
                log(f"Erreur lors du traitement du fichier de verrouillage: {e}", "ERROR")

        # Rechercher et tuer tous les processus nerd-dictation qui seraient encore en cours
        pids = find_dictation_processes()
        for pid in pids:
            try:
                pid = pid.strip()
                if pid:
                    if kill_process(pid):
                        any_process_killed = True
                        time.sleep(0.2)

                        # Vérifier à nouveau et forcer si nécessaire
                        try:
                            os.kill(int(pid), 0)  # Le processus existe toujours
                            kill_process(pid, force=True)
                        except (OSError, ValueError):
                            pass  # Processus déjà terminé ou PID invalide
            except Exception as e:
                log(f"Erreur lors du traitement du PID {pid}: {e}", "ERROR")

        # Nettoyer les fichiers temporaires
        if COOKIE_FILE.exists():
            log("Suppression du fichier cookie...")
            try:
                COOKIE_FILE.unlink()
            except Exception as e:
                log(f"Erreur lors de la suppression du fichier cookie: {e}", "WARNING")

        if any_process_killed:
            log("Dictée arrêtée avec succès.")
            # Envoyer une notification
            send_notification("Nerd-Dictation", "Dictée arrêtée", "normal")
        else:
            log("Aucun processus de dictée n'était en cours d'exécution.")

        return True
    except Exception as e:
        log(f"Erreur générale lors de l'arrêt de la dictée: {e}", "ERROR")
        log(traceback.format_exc(), "DEBUG")
        return False

def check_status():
    """Vérifie le statut actuel de la dictée"""
    try:
        log("Vérification du statut de la dictée...")

        pids = find_dictation_processes()
        if pids:
            log(f"Dictée en cours d'exécution. PIDs: {', '.join(pids)}")
            return True
        else:
            log("Aucune dictée en cours d'exécution.")
            return False
    except Exception as e:
        log(f"Erreur lors de la vérification du statut: {e}", "ERROR")
        log(traceback.format_exc(), "DEBUG")
        return False

def toggle_dictation():
    """Bascule entre démarrage et arrêt de la dictée"""
    try:
        log("Basculement de l'état de la dictée...")

        # Vérifier l'état actuel
        is_running = check_status()

        if is_running:
            log("La dictée est en cours, arrêt...")
            return stop_dictation()
        else:
            log("La dictée n'est pas en cours, démarrage...")
            return start_dictation()
    except Exception as e:
        log(f"Erreur lors du basculement de la dictée: {e}", "ERROR")
        log(traceback.format_exc(), "DEBUG")
        return False

def main():
    """Fonction principale"""
    try:
        if len(sys.argv) < 2:
            log("USAGE: python dictation_control.py [start|stop|toggle|status]", "ERROR")
            return 1

        command = sys.argv[1].lower()

        if command == "start":
            return 0 if start_dictation() else 1
        elif command == "stop":
            return 0 if stop_dictation() else 1
        elif command == "toggle":
            return 0 if toggle_dictation() else 1
        elif command == "status":
            return 0 if check_status() else 1
        else:
            log(f"Commande inconnue: {command}. Utilisez 'start', 'stop', 'toggle' ou 'status'.", "ERROR")
            return 1
    except Exception as e:
        log(f"Erreur dans la fonction principale: {e}", "ERROR")
        log(traceback.format_exc(), "DEBUG")
        return 1

if __name__ == "__main__":
    # Vérifier que le script est exécuté depuis le bon environnement Python
    try:
        import vosk
        log("Module vosk trouvé et importé avec succès", "DEBUG")
    except ImportError:
        log("ERREUR: Module vosk non trouvé. Assurez-vous d'exécuter ce script avec l'interpréteur Python de l'environnement virtuel", "ERROR")
        sys.exit(1)

    sys.exit(main())
