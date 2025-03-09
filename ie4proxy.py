#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Proxy per Internet Explorer 4 che converte automaticamente le connessioni HTTPS in HTTP.
Compatibile con Python 2.x per supportare sistemi operativi più vecchi.
"""

import socket
import select
import re
import threading
import ssl
import time

# Configurazione del proxy
PROXY_HOST = '127.0.0.1'    # Indirizzo locale
PROXY_PORT = 8080           # Porta di ascolto
BUFFER_SIZE = 8192          # Dimensione del buffer
MAX_CONNECTIONS = 10        # Numero massimo di connessioni

class ProxyServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(MAX_CONNECTIONS)
        print("[*] Proxy in ascolto su {}:{}".format(self.host, self.port))
    
    def start(self):
        while True:
            try:
                client_socket, addr = self.server_socket.accept()
                print("[*] Connessione accettata da {}:{}".format(addr[0], addr[1]))
                client_thread = threading.Thread(target=self.handle_client, args=(client_socket,))
                client_thread.daemon = True
                client_thread.start()
            except KeyboardInterrupt:
                print("[*] Interruzione del proxy...")
                break
            except Exception as e:
                print("[!] Errore: {}".format(e))
    
    def handle_client(self, client_socket):
        request = self.receive_data(client_socket)
        if not request:
            client_socket.close()
            return
        
        # Analizza la richiesta HTTP
        first_line = request.split('\n')[0]
        print("[*] Richiesta: {}".format(first_line))
        
        # Estrai l'URL dalla richiesta
        url = first_line.split(' ')[1]
        http_pos = url.find("://")
        if http_pos != -1:
            url = url[(http_pos + 3):]
        
        # Estrai l'host e la porta dalla URL
        port_pos = url.find(":")
        host_pos = url.find("/")
        if host_pos == -1:
            host_pos = len(url)
        
        host = ""
        port = -1
        if port_pos == -1 or host_pos < port_pos:
            port = 80  # Default HTTP port
            host = url[:host_pos]
        else:
            port = int(url[port_pos+1:host_pos])
            host = url[:port_pos]
        
        # Converti HTTPS in HTTP nella richiesta
        modified_request = self.convert_https_to_http(request)
        
        # Crea una connessione al server di destinazione
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.connect((host, port))
            
            # Se la richiesta originale era HTTPS (porta 443), stabilisci una connessione SSL
            if "CONNECT" in first_line and ":443" in first_line:
                # Invia una risposta positiva al client per il tunnel CONNECT
                tunnel_response = "HTTP/1.1 200 Connection established\r\n\r\n"
                client_socket.send(tunnel_response.encode())
                
                try:
                    # Tenta di stabilire una connessione SSL con il server di destinazione
                    server_socket = ssl.wrap_socket(server_socket)
                    
                    # Costruisci una nuova richiesta HTTP
                    path = url[host_pos:]
                    if not path:
                        path = "/"
                    
                    # Crea una nuova richiesta GET standard
                    new_request = "GET {} HTTP/1.1\r\nHost: {}\r\n".format(path, host)
                    # Aggiungi le altre intestazioni dalla richiesta originale
                    for line in modified_request.split('\n')[1:]:
                        if line.strip() and not line.startswith("Proxy-"):
                            new_request += line + "\r\n"
                    
                    new_request += "\r\n"
                    server_socket.send(new_request.encode())
                except Exception as e:
                    print("[!] Errore SSL: {}".format(e))
                    client_socket.close()
                    server_socket.close()
                    return
            else:
                # Per le richieste HTTP normali, inoltra semplicemente la richiesta modificata
                server_socket.send(modified_request.encode())
            
            # Gestisci il trasferimento dati tra client e server
            self.transfer_data(client_socket, server_socket)
            
        except Exception as e:
            print("[!] Errore di connessione: {}".format(e))
        finally:
            if server_socket:
                server_socket.close()
            if client_socket:
                client_socket.close()
    
    def receive_data(self, socket, max_tries=3):
        data = ""
        tries = 0
        while tries < max_tries:
            try:
                chunk = socket.recv(BUFFER_SIZE).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                data += chunk
                if len(chunk) < BUFFER_SIZE:
                    break
            except Exception:
                tries += 1
                time.sleep(0.1)
        return data
    
    def transfer_data(self, client, server):
        sockets = [client, server]
        timeout = 60  # 60 secondi di timeout
        
        while True:
            # Attendi che qualcuno dei socket sia pronto per la lettura
            input_ready, _, _ = select.select(sockets, [], [], timeout)
            
            if not input_ready:  # Timeout
                break
            
            for sock in input_ready:
                try:
                    data = sock.recv(BUFFER_SIZE)
                    if not data:
                        return
                    
                    # Determina il socket di destinazione
                    if sock is client:
                        # Dati dal client al server
                        # Converti eventuali link HTTPS in HTTP nei dati
                        data = self.convert_https_links_in_data(data)
                        server.send(data)
                    else:
                        # Dati dal server al client
                        # Converti eventuali link HTTPS in HTTP nella risposta
                        data = self.convert_https_links_in_data(data)
                        client.send(data)
                except Exception as e:
                    print("[!] Errore di trasferimento: {}".format(e))
                    return
    
    def convert_https_to_http(self, request):
        # Converti le richieste CONNECT (HTTPS) in GET (HTTP)
        if "CONNECT" in request.split('\n')[0]:
            lines = request.split('\n')
            connect_line = lines[0]
            host_port = connect_line.split(' ')[1]
            
            # Costruisci una nuova richiesta GET
            host = host_port.split(':')[0]
            new_first_line = "GET / HTTP/1.1"
            lines[0] = new_first_line
            
            # Aggiungi o aggiorna l'intestazione Host
            has_host = False
            for i, line in enumerate(lines):
                if line.lower().startswith("host:"):
                    lines[i] = "Host: " + host
                    has_host = True
                    break
            
            if not has_host:
                lines.insert(1, "Host: " + host)
            
            return '\n'.join(lines)
        
        # Converti i riferimenti a HTTPS in HTTP nelle intestazioni
        return request.replace("https://", "http://")
    
    def convert_https_links_in_data(self, data):
        # Converti i link HTTPS in HTTP nei dati
        try:
            decoded_data = data.decode('utf-8', errors='ignore')
            # Conversione dei link HTML <a href="https://...">
            decoded_data = re.sub(r'href=["\']https://', r'href="http://', decoded_data)
            # Conversione dei link HTML <img src="https://...">
            decoded_data = re.sub(r'src=["\']https://', r'src="http://', decoded_data)
            # Conversione delle URL assolute in CSS e JS
            decoded_data = re.sub(r'url\(["\']?https://', r'url("http://', decoded_data)
            # Conversione generica di https:// in http://
            decoded_data = decoded_data.replace("https://", "http://")
            return decoded_data.encode('utf-8', errors='ignore')
        except Exception:
            # Se si verifica un errore nella decodifica (dati binari), restituisci i dati originali
            return data

if __name__ == "__main__":
    try:
        proxy = ProxyServer(PROXY_HOST, PROXY_PORT)
        print("[*] Configurazione del proxy completata")
        print("[*] Per usare questo proxy in Internet Explorer 4:")
        print("    1. Apri Internet Explorer 4")
        print("    2. Vai su Visualizza -> Opzioni Internet -> Connessione")
        print("    3. Spunta 'Utilizza server proxy'")
        print("    4. Inserisci: {}:{}".format(PROXY_HOST, PROXY_PORT))
        print("[*] Premi Ctrl+C per terminare il proxy")
        proxy.start()
    except KeyboardInterrupt:
        print("[*] Proxy terminato")
    except Exception as e:
        print("[!] Errore critico: {}".format(e))