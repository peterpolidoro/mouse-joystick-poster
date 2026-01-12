;; channels.scm — Guix channel configuration for this repo
;;
;; For maximum reproducibility, pin this file to a specific Guix revision:
;;   make lock-channels
;;   git add guix/channels.scm && git commit -m "Pin Guix channel revision"
;;
;; Until you pin it, this file follows the current default Guix channel.

(list (channel
        (name 'guix)
        (url "https://git.savannah.gnu.org/git/guix.git")
        ;; 'introduction' helps verify the channel's authenticity.
        (introduction
         (make-channel-introduction
          "9edb3f66fd807b096b48283debdcddccfea34bad"
          (openpgp-fingerprint
           "BBB0 2DDF 2E4B 2A10 9C64  DEB5 7E73 9D43 4EFA 9F7A")))))
