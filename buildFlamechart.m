function handles = buildFlamechart(ax, callSequence, options)
% BUILDFLAMECHART Render a flamechart visualization of the call sequence.
%
%   handles = buildFlamechart(ax, callSequence)
%   handles = buildFlamechart(ax, callSequence, options)
%
%   Inputs:
%     ax           - Target axes handle
%     callSequence - struct array from parseProfilerPhases (enter/exit events with depth)
%     options      - (optional) struct with fields:
%       .highlightName - function name to highlight (default: '')
%       .colormap      - Nx3 colormap matrix (default: lines(256))
%
%   Output:
%     handles - struct array with fields: rect, text, funcName, seqIndex
%               One entry per "enter" event that has a matching "exit".

    if nargin < 3
        options = struct();
    end

    highlightName = getOpt(options, 'highlightName', '');
    cmap          = getOpt(options, 'colormap', lines(256));

    cla(ax);
    hold(ax, 'on');

    nEntries = numel(callSequence);
    if nEntries == 0
        title(ax, 'No data to display');
        return;
    end

    % We need to pair enter/exit events to draw rectangles.
    % Build rectangles for each "enter" by finding its matching "exit".
    % Use a stack-based approach.
    maxDepth = 0;
    rects = struct('x', {}, 'width', {}, 'depth', {}, 'funcName', {}, 'fileName', {}, 'seqIndex', {});
    rectIdx = 0;

    % Map sequence position to an x-coordinate.
    % We track the x position as a running counter of enter events.
    enterCount = 0;
    % Stack: each entry is [enterXPos, depth, seqIndex, funcName, fileName]
    stack = {};

    for k = 1:nEntries
        entry = callSequence(k);
        if strcmp(entry.event, 'enter')
            enterCount = enterCount + 1;
            stack{end+1} = struct('xStart', enterCount, 'depth', entry.depth, ...
                                  'seqIndex', entry.index, 'funcName', entry.funcName, ...
                                  'fileName', entry.fileName); %#ok<AGROW>
            if entry.depth > maxDepth
                maxDepth = entry.depth;
            end
        elseif strcmp(entry.event, 'exit') && ~isempty(stack)
            % Pop the most recent matching entry from the stack
            % Find the topmost stack entry with the same funcName
            popIdx = numel(stack);
            for s = numel(stack):-1:1
                if strcmp(stack{s}.funcName, entry.funcName)
                    popIdx = s;
                    break;
                end
            end
            info = stack{popIdx};
            stack(popIdx) = [];

            rectIdx = rectIdx + 1;
            rects(rectIdx).x        = info.xStart;
            rects(rectIdx).width    = enterCount - info.xStart + 1;
            rects(rectIdx).depth    = info.depth;
            rects(rectIdx).funcName = info.funcName;
            rects(rectIdx).fileName = info.fileName;
            rects(rectIdx).seqIndex = info.seqIndex;
        end
    end

    % Also flush any remaining stack entries (unmatched enters)
    for s = 1:numel(stack)
        info = stack{s};
        rectIdx = rectIdx + 1;
        rects(rectIdx).x        = info.xStart;
        rects(rectIdx).width    = enterCount - info.xStart + 1;
        rects(rectIdx).depth    = info.depth;
        rects(rectIdx).funcName = info.funcName;
        rects(rectIdx).fileName = info.fileName;
        rects(rectIdx).seqIndex = info.seqIndex;
    end

    if rectIdx == 0
        title(ax, 'No rectangles to draw');
        return;
    end

    % Assign colors by function name
    uniqueNames = unique({rects.funcName});
    nColors = size(cmap, 1);
    colorMap = containers.Map();
    for k = 1:numel(uniqueNames)
        cidx = mod(k - 1, nColors) + 1;
        colorMap(uniqueNames{k}) = cmap(cidx, :);
    end

    % Draw rectangles
    handles = struct('rect', {}, 'text', {}, 'funcName', {}, 'seqIndex', {}, 'fileName', {});
    barHeight = 0.85;

    for k = 1:rectIdx
        r = rects(k);
        xPos = r.x - 0.5;
        yPos = r.depth - 1;
        w = r.width;
        h = barHeight;

        faceColor = colorMap(r.funcName);

        % Highlight if requested
        if ~isempty(highlightName) && contains(r.funcName, highlightName, 'IgnoreCase', true)
            edgeColor = [1 0 0];
            lineWidth = 2.5;
        else
            edgeColor = [0.3 0.3 0.3];
            lineWidth = 0.5;
        end

        rectH = rectangle(ax, 'Position', [xPos, yPos, w, h], ...
            'FaceColor', faceColor, 'EdgeColor', edgeColor, ...
            'LineWidth', lineWidth, 'Curvature', [0.05, 0.05]);

        % Add text label if rectangle is wide enough
        textH = [];
        if w > 2
            % Truncate label if needed
            label = r.funcName;
            textH = text(ax, xPos + w/2, yPos + h/2, label, ...
                'HorizontalAlignment', 'center', 'VerticalAlignment', 'middle', ...
                'FontSize', 7, 'Interpreter', 'none', 'Clipping', 'on');
        end

        idx = numel(handles) + 1;
        handles(idx).rect     = rectH;
        handles(idx).text     = textH;
        handles(idx).funcName = r.funcName;
        handles(idx).seqIndex = r.seqIndex;
        handles(idx).fileName = r.fileName;

        % Store metadata for click callback
        rectH.UserData = struct('funcName', r.funcName, 'fileName', r.fileName, ...
                                'seqIndex', r.seqIndex, 'depth', r.depth);
    end

    hold(ax, 'off');

    % Configure axes
    ax.YDir = 'reverse';
    ax.XLim = [0, enterCount + 1];
    ax.YLim = [0, maxDepth + 1];
    xlabel(ax, 'Call Sequence Position');
    ylabel(ax, 'Call Depth');
    title(ax, 'Flamechart');
    ax.TickLabelInterpreter = 'none';

    % Enable interactive navigation
    zoom(ancestor(ax, 'figure'), 'on');
end

function val = getOpt(opts, fieldName, default)
    if isfield(opts, fieldName)
        val = opts.(fieldName);
    else
        val = default;
    end
end
