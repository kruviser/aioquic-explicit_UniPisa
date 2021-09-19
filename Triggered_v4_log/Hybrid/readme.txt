Flusso dei log lato server nel seguente ordine:

1) server_ip_4.txt --> comunicazione lato server pre 1a migrazione
2) serverCoAP_ip_4.txt --> log lato CoAP server sulla 172.16.4.4 dove viene lanciato il comando di migrazione del container di questa vm verso la 172.16.4.232 (1a migrazione)
3) migration_ip_232.txt --> log lato vm 172.16.4.232 riguardo la ricezione del container durante la 1a migrazione
4) server_ip_232.txt --> comunicazione lato server post 1a migrazione e pre 2a migrazione
5) serverCoAP_ip_232.txt --> log lato CoAP server sulla 172.16.4.232 dove viene lanciato il comando di migrazione del container di questa vm verso la 172.16.4.4 (2a migrazione)
6) migration_ip_4.txt --> log lato vm 172.16.4.4 riguardo la ricezione del container durante la 2a migrazione
7) server_ip_4.txt --> nella parte finale del file è presenta la comunicazione lato server post 2a migrazione