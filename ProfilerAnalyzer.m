classdef ProfilerAnalyzer < handle
% PROFILERANALYZER Interactive MATLAB profiler analysis tool.
%
%   app = ProfilerAnalyzer()        % Launch with file picker
%   app = ProfilerAnalyzer(matFile) % Launch with specified .mat file
%
%   Analyzes profiler data by slicing function call sequences between
%   calls to a phase boundary function (default: 'phase_iterator').
%   Provides filtering, searching, flamechart, call graph, and
%   codebase coverage analysis.

    properties (Access = private)
        % UI Components
        Fig
        MainGrid
        TopPanel
        FilterPanel
        ContentGrid
        LeftPanel
        RightPanel

        % Top bar controls
        LoadButton
        CodebaseDirButton
        PhaseStartField
        PhaseEndField
        PhaseGoButton
        PhaseInfoLabel

        % Filter controls
        HideBuiltinsCheck
        HideMatlabCheck
        ExcludeListBox
        ExcludeAddButton
        ExcludeRemoveButton
        SearchField
        SearchPrevButton
        SearchNextButton
        SearchMatchLabel

        % Main table
        CallTable

        % Right panel tabs
        TabGroup
        FlamechartTab
        FlamechartAxes
        CallGraphTab
        CallGraphAxes
        GraphLayoutDropdown
        CoverageTab
        CoverageAxes
        CoverageTable
        CoverageFilterCheck
        CoveragePctLabel

        % Data
        MatFilePath
        CodebaseDir
        ParseResult
        FilteredSequence
        FlamechartHandles
        SearchMatches
        SearchIndex
        ExcludeList
        CoverageResult
    end

    methods (Access = public)
        function app = ProfilerAnalyzer(matFile)
            app.ExcludeList = {};
            app.SearchMatches = [];
            app.SearchIndex = 0;

            buildUI(app);

            if nargin >= 1 && ~isempty(matFile)
                app.MatFilePath = matFile;
                loadData(app);
            end
        end
    end

    methods (Access = private)

        function buildUI(app)
            % Create main figure
            app.Fig = uifigure('Name', 'Profiler Analyzer', ...
                'Position', [50 50 1400 800], ...
                'AutoResizeChildren', 'off', ...
                'CloseRequestFcn', @(~,~) delete(app.Fig));

            % Main vertical grid: top bar | filter bar | content
            app.MainGrid = uigridlayout(app.Fig, [3 1], ...
                'RowHeight', {40, 50, '1x'}, 'Padding', [5 5 5 5], 'RowSpacing', 3);

            % === TOP BAR ===
            topGrid = uigridlayout(app.MainGrid, [1 8], ...
                'ColumnWidth', {100, 120, 80, 60, 80, 60, 100, '1x'}, ...
                'Padding', [2 2 2 2]);
            topGrid.Layout.Row = 1;

            app.LoadButton = uibutton(topGrid, 'Text', 'Load .mat', ...
                'ButtonPushedFcn', @(~,~) onLoadFile(app));
            app.LoadButton.Layout.Column = 1;

            app.CodebaseDirButton = uibutton(topGrid, 'Text', 'Codebase Dir', ...
                'ButtonPushedFcn', @(~,~) onSelectCodebaseDir(app));
            app.CodebaseDirButton.Layout.Column = 2;

            uilabel(topGrid, 'Text', 'Start Phase:', 'HorizontalAlignment', 'right').Layout.Column = 3;
            app.PhaseStartField = uieditfield(topGrid, 'numeric', 'Value', 1, ...
                'Limits', [1 Inf], 'RoundFractionalValues', 'on');
            app.PhaseStartField.Layout.Column = 4;

            uilabel(topGrid, 'Text', 'End Phase:', 'HorizontalAlignment', 'right').Layout.Column = 5;
            app.PhaseEndField = uieditfield(topGrid, 'numeric', 'Value', 1, ...
                'Limits', [1 Inf], 'RoundFractionalValues', 'on');
            app.PhaseEndField.Layout.Column = 6;

            app.PhaseGoButton = uibutton(topGrid, 'Text', 'Analyze', ...
                'ButtonPushedFcn', @(~,~) onAnalyze(app));
            app.PhaseGoButton.Layout.Column = 7;

            app.PhaseInfoLabel = uilabel(topGrid, 'Text', 'No data loaded', ...
                'HorizontalAlignment', 'left');
            app.PhaseInfoLabel.Layout.Column = 8;

            % === FILTER BAR ===
            filterGrid = uigridlayout(app.MainGrid, [1 11], ...
                'ColumnWidth', {100, 120, 60, 120, 60, 60, 20, 200, 60, 60, '1x'}, ...
                'Padding', [2 2 2 2]);
            filterGrid.Layout.Row = 2;

            app.HideBuiltinsCheck = uicheckbox(filterGrid, 'Text', 'Hide Builtins', ...
                'Value', false, 'ValueChangedFcn', @(~,~) applyFilters(app));
            app.HideBuiltinsCheck.Layout.Column = 1;

            app.HideMatlabCheck = uicheckbox(filterGrid, 'Text', 'Hide matlabroot', ...
                'Value', false, 'ValueChangedFcn', @(~,~) applyFilters(app));
            app.HideMatlabCheck.Layout.Column = 2;

            app.ExcludeAddButton = uibutton(filterGrid, 'Text', '+Excl', ...
                'ButtonPushedFcn', @(~,~) onAddExclusion(app));
            app.ExcludeAddButton.Layout.Column = 3;

            app.ExcludeListBox = uidropdown(filterGrid, 'Items', {'(none)'}, ...
                'Editable', 'off');
            app.ExcludeListBox.Layout.Column = 4;

            app.ExcludeRemoveButton = uibutton(filterGrid, 'Text', '-Excl', ...
                'ButtonPushedFcn', @(~,~) onRemoveExclusion(app));
            app.ExcludeRemoveButton.Layout.Column = 5;

            uilabel(filterGrid, 'Text', '|').Layout.Column = 6;

            uilabel(filterGrid, 'Text', '').Layout.Column = 7;

            app.SearchField = uieditfield(filterGrid, 'text', 'Placeholder', 'Search function...', ...
                'ValueChangedFcn', @(~,~) onSearch(app));
            app.SearchField.Layout.Column = 8;

            app.SearchPrevButton = uibutton(filterGrid, 'Text', '< Prev', ...
                'ButtonPushedFcn', @(~,~) onSearchPrev(app));
            app.SearchPrevButton.Layout.Column = 9;

            app.SearchNextButton = uibutton(filterGrid, 'Text', 'Next >', ...
                'ButtonPushedFcn', @(~,~) onSearchNext(app));
            app.SearchNextButton.Layout.Column = 10;

            app.SearchMatchLabel = uilabel(filterGrid, 'Text', '', ...
                'HorizontalAlignment', 'left');
            app.SearchMatchLabel.Layout.Column = 11;

            % === CONTENT AREA ===
            app.ContentGrid = uigridlayout(app.MainGrid, [1 2], ...
                'ColumnWidth', {'1x', '1x'}, 'Padding', [0 0 0 0]);
            app.ContentGrid.Layout.Row = 3;

            % Left panel: call sequence table
            leftGrid = uigridlayout(app.ContentGrid, [1 1], 'Padding', [2 2 2 2]);
            leftGrid.Layout.Column = 1;

            app.CallTable = uitable(leftGrid, ...
                'ColumnName', {'Seq', 'Event', 'Function', 'File', 'Type', 'Depth'}, ...
                'ColumnWidth', {40, 45, 200, 'auto', 80, 45}, ...
                'ColumnSortable', [true true true true true true], ...
                'RowStriping', 'on', ...
                'CellSelectionCallback', @(src,evt) onTableSelect(app, src, evt), ...
                'DoubleClickedFcn', @(src,evt) onTableDoubleClick(app, src, evt));

            % Right panel: tabs
            rightGrid = uigridlayout(app.ContentGrid, [1 1], 'Padding', [2 2 2 2]);
            rightGrid.Layout.Column = 2;

            app.TabGroup = uitabgroup(rightGrid);

            % Flamechart tab
            app.FlamechartTab = uitab(app.TabGroup, 'Title', 'Flamechart');
            flameGrid = uigridlayout(app.FlamechartTab, [1 1], 'Padding', [2 2 2 2]);
            app.FlamechartAxes = uiaxes(flameGrid);

            % Call graph tab
            app.CallGraphTab = uitab(app.TabGroup, 'Title', 'Call Graph');
            graphGrid = uigridlayout(app.CallGraphTab, [2 1], ...
                'RowHeight', {30, '1x'}, 'Padding', [2 2 2 2]);
            graphControlGrid = uigridlayout(graphGrid, [1 2], ...
                'ColumnWidth', {80, 120}, 'Padding', [0 0 0 0]);
            graphControlGrid.Layout.Row = 1;
            uilabel(graphControlGrid, 'Text', 'Layout:');
            app.GraphLayoutDropdown = uidropdown(graphControlGrid, ...
                'Items', {'layered', 'force', 'circle', 'subspace'}, ...
                'Value', 'layered', ...
                'ValueChangedFcn', @(~,~) refreshCallGraph(app));
            app.CallGraphAxes = uiaxes(graphGrid);
            app.CallGraphAxes.Layout.Row = 2;

            % Coverage tab
            app.CoverageTab = uitab(app.TabGroup, 'Title', 'Coverage');
            covGrid = uigridlayout(app.CoverageTab, [3 1], ...
                'RowHeight', {30, 80, '1x'}, 'Padding', [2 2 2 2]);

            covControlGrid = uigridlayout(covGrid, [1 3], ...
                'ColumnWidth', {200, 150, '1x'}, 'Padding', [0 0 0 0]);
            covControlGrid.Layout.Row = 1;
            app.CoveragePctLabel = uilabel(covControlGrid, 'Text', 'No codebase loaded', ...
                'FontWeight', 'bold', 'FontSize', 14);
            app.CoveragePctLabel.Layout.Column = 1;
            app.CoverageFilterCheck = uicheckbox(covControlGrid, ...
                'Text', 'Show uncalled only', 'Value', false, ...
                'ValueChangedFcn', @(~,~) refreshCoverageTable(app));
            app.CoverageFilterCheck.Layout.Column = 2;

            app.CoverageAxes = uiaxes(covGrid);
            app.CoverageAxes.Layout.Row = 2;

            app.CoverageTable = uitable(covGrid, ...
                'ColumnName', {'Function', 'File', 'Called', 'Call Count'}, ...
                'ColumnWidth', {150, 'auto', 60, 70}, ...
                'ColumnSortable', [true true true true], ...
                'DoubleClickedFcn', @(src,evt) onCoverageDoubleClick(app, src, evt));
            app.CoverageTable.Layout.Row = 3;
        end

        % === DATA LOADING ===

        function onLoadFile(app)
            [file, path] = uigetfile('*.mat', 'Select Profiler .mat File');
            if isequal(file, 0)
                return;
            end
            app.MatFilePath = fullfile(path, file);
            loadData(app);
        end

        function loadData(app)
            try
                % Quick parse to get phase count
                opts = struct('hideBuiltins', false, 'hideMatlabroot', false, ...
                              'excludeNames', {app.ExcludeList});
                result = parseProfilerPhases(app.MatFilePath, 1, 1, opts);
                app.PhaseInfoLabel.Text = sprintf('Loaded: %d phases detected', result.totalPhases);
                app.PhaseEndField.Value = min(result.totalPhases, 1);
                app.ParseResult = result;
            catch ex
                uialert(app.Fig, ex.message, 'Load Error');
            end
        end

        function onAnalyze(app)
            if isempty(app.MatFilePath)
                uialert(app.Fig, 'No .mat file loaded.', 'Error');
                return;
            end

            startP = app.PhaseStartField.Value;
            endP   = app.PhaseEndField.Value;

            try
                opts = struct('hideBuiltins', app.HideBuiltinsCheck.Value, ...
                              'hideMatlabroot', app.HideMatlabCheck.Value, ...
                              'excludeNames', {app.ExcludeList});
                app.ParseResult = parseProfilerPhases(app.MatFilePath, startP, endP, opts);
                app.FilteredSequence = app.ParseResult.callSequence;

                app.PhaseInfoLabel.Text = sprintf('Phases %d-%d | %d events | %d total phases', ...
                    startP, endP, numel(app.FilteredSequence), app.ParseResult.totalPhases);

                updateTable(app);
                refreshFlamechart(app);
                refreshCallGraph(app);

                if ~isempty(app.CodebaseDir)
                    refreshCoverage(app);
                end
            catch ex
                uialert(app.Fig, ex.message, 'Analysis Error');
            end
        end

        % === FILTERING ===

        function applyFilters(app)
            % Re-run analysis with current filter settings
            onAnalyze(app);
        end

        function onAddExclusion(app)
            % Get function name from selected table row or prompt
            answer = inputdlg('Function name to exclude:', 'Add Exclusion', [1 40]);
            if isempty(answer) || isempty(strtrim(answer{1}))
                return;
            end
            funcName = strtrim(answer{1});
            if ~any(strcmpi(app.ExcludeList, funcName))
                app.ExcludeList{end+1} = funcName;
            end
            updateExcludeDropdown(app);
            applyFilters(app);
        end

        function onRemoveExclusion(app)
            if isempty(app.ExcludeList)
                return;
            end
            selected = app.ExcludeListBox.Value;
            if strcmp(selected, '(none)')
                return;
            end
            app.ExcludeList(strcmpi(app.ExcludeList, selected)) = [];
            updateExcludeDropdown(app);
            applyFilters(app);
        end

        function updateExcludeDropdown(app)
            if isempty(app.ExcludeList)
                app.ExcludeListBox.Items = {'(none)'};
            else
                app.ExcludeListBox.Items = app.ExcludeList;
            end
        end

        % === TABLE ===

        function updateTable(app)
            seq = app.FilteredSequence;
            if isempty(seq)
                app.CallTable.Data = {};
                return;
            end

            n = numel(seq);
            data = cell(n, 6);
            for k = 1:n
                data{k, 1} = seq(k).index;
                data{k, 2} = seq(k).event;
                data{k, 3} = seq(k).funcName;
                data{k, 4} = seq(k).fileName;
                data{k, 5} = seq(k).funcType;
                data{k, 6} = seq(k).depth;
            end
            app.CallTable.Data = data;
        end

        function onTableSelect(app, ~, evt)
            if isempty(evt.Indices)
                return;
            end
            row = evt.Indices(1);
            % Highlight corresponding flamechart rectangle
            if ~isempty(app.FlamechartHandles) && row <= numel(app.FilteredSequence)
                funcName = app.FilteredSequence(row).funcName;
                highlightFlamechartByName(app, funcName);
            end
        end

        function onTableDoubleClick(app, ~, evt)
            if isempty(evt.InteractionInformation.Row)
                return;
            end
            row = evt.InteractionInformation.Row;
            seq = app.FilteredSequence;
            if row <= numel(seq) && ~isempty(seq(row).fileName)
                try
                    edit(seq(row).fileName);
                catch
                    % File may not exist or be accessible
                end
            end
        end

        % === SEARCH ===

        function onSearch(app)
            query = app.SearchField.Value;
            if isempty(query) || isempty(app.FilteredSequence)
                app.SearchMatches = [];
                app.SearchIndex = 0;
                app.SearchMatchLabel.Text = '';
                return;
            end

            seq = app.FilteredSequence;
            matches = [];
            for k = 1:numel(seq)
                if ~isempty(regexpi(seq(k).funcName, query, 'once'))
                    matches(end+1) = k; %#ok<AGROW>
                end
            end

            app.SearchMatches = matches;
            if isempty(matches)
                app.SearchIndex = 0;
                app.SearchMatchLabel.Text = '0 matches';
            else
                app.SearchIndex = 1;
                app.SearchMatchLabel.Text = sprintf('1 of %d', numel(matches));
                scrollToMatch(app);
            end
        end

        function onSearchNext(app)
            if isempty(app.SearchMatches)
                return;
            end
            app.SearchIndex = app.SearchIndex + 1;
            if app.SearchIndex > numel(app.SearchMatches)
                app.SearchIndex = 1;  % wrap around
            end
            app.SearchMatchLabel.Text = sprintf('%d of %d', app.SearchIndex, numel(app.SearchMatches));
            scrollToMatch(app);
        end

        function onSearchPrev(app)
            if isempty(app.SearchMatches)
                return;
            end
            app.SearchIndex = app.SearchIndex - 1;
            if app.SearchIndex < 1
                app.SearchIndex = numel(app.SearchMatches);  % wrap around
            end
            app.SearchMatchLabel.Text = sprintf('%d of %d', app.SearchIndex, numel(app.SearchMatches));
            scrollToMatch(app);
        end

        function scrollToMatch(app)
            if app.SearchIndex == 0 || isempty(app.SearchMatches)
                return;
            end
            matchRow = app.SearchMatches(app.SearchIndex);

            % Highlight the row by selecting it using scroll
            scroll(app.CallTable, 'row', matchRow);

            % Also highlight in flamechart
            funcName = app.FilteredSequence(matchRow).funcName;
            highlightFlamechartByName(app, funcName);
        end

        % === FLAMECHART ===

        function refreshFlamechart(app)
            if isempty(app.FilteredSequence)
                cla(app.FlamechartAxes);
                return;
            end
            opts = struct();
            query = app.SearchField.Value;
            if ~isempty(query)
                opts.highlightName = query;
            end
            app.FlamechartHandles = buildFlamechart(app.FlamechartAxes, app.FilteredSequence, opts);

            % Add click callbacks to all rectangles
            for k = 1:numel(app.FlamechartHandles)
                h = app.FlamechartHandles(k);
                if ~isempty(h.rect) && isvalid(h.rect)
                    h.rect.ButtonDownFcn = @(src,~) onFlamechartClick(app, src);
                end
            end
        end

        function onFlamechartClick(app, src)
            if ~isempty(src.UserData)
                funcName = src.UserData.funcName;
                fileName = src.UserData.fileName;

                % Highlight in table
                highlightTableByName(app, funcName);

                % Show info
                app.PhaseInfoLabel.Text = sprintf('Selected: %s', funcName);

                % If double-clicked-like, open the file
                % (single click just highlights)
            end
        end

        function highlightFlamechartByName(app, funcName)
            if isempty(app.FlamechartHandles)
                return;
            end
            for k = 1:numel(app.FlamechartHandles)
                h = app.FlamechartHandles(k);
                if ~isempty(h.rect) && isvalid(h.rect)
                    if strcmpi(h.funcName, funcName)
                        h.rect.EdgeColor = [1 0 0];
                        h.rect.LineWidth = 2.5;
                    else
                        h.rect.EdgeColor = [0.3 0.3 0.3];
                        h.rect.LineWidth = 0.5;
                    end
                end
            end
        end

        function highlightTableByName(app, funcName)
            seq = app.FilteredSequence;
            for k = 1:numel(seq)
                if strcmpi(seq(k).funcName, funcName)
                    scroll(app.CallTable, 'row', k);
                    return;
                end
            end
        end

        % === CALL GRAPH ===

        function refreshCallGraph(app)
            if isempty(app.FilteredSequence)
                cla(app.CallGraphAxes);
                return;
            end
            opts = struct('layout', app.GraphLayoutDropdown.Value);
            query = app.SearchField.Value;
            if ~isempty(query)
                opts.highlightName = query;
            end
            buildCallGraph(app.CallGraphAxes, app.FilteredSequence, opts);
        end

        % === COVERAGE ===

        function onSelectCodebaseDir(app)
            dirPath = uigetdir('', 'Select Codebase Root Directory');
            if isequal(dirPath, 0)
                return;
            end
            app.CodebaseDir = dirPath;
            if ~isempty(app.ParseResult)
                refreshCoverage(app);
            end
        end

        function refreshCoverage(app)
            if isempty(app.CodebaseDir) || isempty(app.ParseResult)
                return;
            end

            try
                app.CoverageResult = scanCodebaseCoverage(app.CodebaseDir, ...
                    app.FilteredSequence, app.ParseResult.functionTable);

                % Update percentage label
                app.CoveragePctLabel.Text = sprintf('Coverage: %.1f%% (%d / %d functions)', ...
                    app.CoverageResult.coveragePercent, ...
                    numel(app.CoverageResult.calledFunctions), ...
                    numel(app.CoverageResult.codebaseFunctions));

                % Draw bar chart
                drawCoverageBar(app);

                % Update table
                refreshCoverageTable(app);
            catch ex
                uialert(app.Fig, ex.message, 'Coverage Error');
            end
        end

        function drawCoverageBar(app)
            ax = app.CoverageAxes;
            cla(ax);

            if isempty(app.CoverageResult)
                return;
            end

            nCalled   = numel(app.CoverageResult.calledFunctions);
            nUncalled = numel(app.CoverageResult.uncalledFunctions);
            nTotal    = nCalled + nUncalled;

            if nTotal == 0
                return;
            end

            hold(ax, 'on');
            barh(ax, 1, nCalled, 'FaceColor', [0.2 0.7 0.3], 'EdgeColor', 'none');
            barh(ax, 1, nTotal, 'FaceColor', [0.8 0.2 0.2], 'EdgeColor', 'none');
            % Redraw called on top
            barh(ax, 1, nCalled, 'FaceColor', [0.2 0.7 0.3], 'EdgeColor', 'none');
            hold(ax, 'off');

            ax.YTick = [];
            ax.XLim = [0 nTotal];
            xlabel(ax, 'Functions');
            legend(ax, {'Called', 'Total'}, 'Location', 'northeast', 'FontSize', 8);
            title(ax, '');
        end

        function refreshCoverageTable(app)
            if isempty(app.CoverageResult)
                return;
            end

            tbl = app.CoverageResult.coverageTable;

            if app.CoverageFilterCheck.Value
                mask = strcmp(tbl.Called, 'No');
                tbl = tbl(mask, :);
            end

            app.CoverageTable.Data = table2cell(tbl);
        end

        function onCoverageDoubleClick(app, ~, evt)
            if isempty(evt.InteractionInformation.Row) || isempty(app.CoverageResult)
                return;
            end
            row = evt.InteractionInformation.Row;
            tbl = app.CoverageResult.coverageTable;

            if app.CoverageFilterCheck.Value
                mask = strcmp(tbl.Called, 'No');
                tbl = tbl(mask, :);
            end

            if row <= height(tbl)
                filePath = tbl.File{row};
                if ~isempty(filePath) && isfile(filePath)
                    try
                        edit(filePath);
                    catch
                    end
                end
            end
        end
    end
end
