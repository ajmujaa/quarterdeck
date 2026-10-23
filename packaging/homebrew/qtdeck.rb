# Homebrew formula for Quarterdeck @VERSION@ (the version comes from the URL). A tap keeps only this file.
# The three @...@ words are filled in by bin/release.py from a real tarball; nothing here is published until the owner does it (packaging/README.md).
class Qtdeck < Formula
  desc "Local dashboard and crew of agents for your software projects"
  homepage "https://github.com/ajmujaa/quarterdeck"
  url "@URL@"
  sha256 "@SHA256@"
  license "Apache-2.0"

  depends_on "gh"
  depends_on "git"
  depends_on "jq"
  depends_on "python@3.12"

  def install
    # The whole program tree goes into libexec; the command in bin is a two-line script that runs it.
    libexec.install Dir["*"]
    (bin/"qtdeck").write <<~EOS
      #!/bin/bash
      PATH="#{formula_opt_libexec("python@3.12")}/bin:$PATH" exec "#{libexec}/bin/qtdeck" "$@"
    EOS
    chmod 0755, bin/"qtdeck"
  end

  def caveats
    <<~EOS
      Run this once to check your tools and make your data folder (it installs nothing):
        qtdeck setup
      Then start the dashboard:
        qtdeck dashboard
    EOS
  end

  test do
    assert_match "Usage: qtdeck", shell_output("#{bin}/qtdeck help")
  end
end
