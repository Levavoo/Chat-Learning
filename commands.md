git clone #get the project in working(local) directory
cd to repo
git branch (check your branch)
git checkout -b example-tutorial-branch creating own branch (-b for new branch)
git status ( what is new and now commited yet)
git add ( Add the README.md file to the staging area. The staging area is where you put files before you commit them.)
git status( verify things are staged ) 
git commit -m "I added text to the README file" ( -m is commiz message)
git push origin example-tutorial-branch 

irrelevvant for now : 
git checkout main
git merge example-tutorial-branch
git push

git diff --staged
	Show differences between versions. --staged	Compare the changes prepared with git add against the last commit.

git mv README.md README.backup.md renames readme, stages change for next commit, like skipping add i assume


-----

start working : 
wsl
cd ~/projects/digibro-monorepo
pwd - check location
code .

git status
git branch --show-current
git fetch origin
git log --oneline --graph --decorate -8
Part	Meaning
git log	Shows commit history, newest first
--oneline	Shows each commit on one line (short hash + message)
--graph	Draws an ASCII graph of branches and merges
--decorate	Shows branch names, tags, and HEAD next to commits
-8	Limits the output to 8 commits


git pull --ff-only origin main